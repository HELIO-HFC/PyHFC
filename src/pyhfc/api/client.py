# SPDX-License-Identifier: EUPL-1.2
"""Client of the HELIO Query Interface (HQI) of the Heliophysics Feature Catalogue.

The HQI is a SOAP web service returning VOTables. Its methods are wrapped by
:class:`HQIClient`::

    from pyhfc.api import HQIClient

    hqi = HQIClient()
    response = hqi.select("VIEW_AR_HQI", what="DATE_OBS, NOAA_NUMBER", limit=10)
    for row in response:
        print(row["DATE_OBS"], row["NOAA_NUMBER"])

@author: Xavier Bonnin for LIRA 11-03-2013
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from importlib.resources import files
from typing import Any, Protocol

import suds
import suds.client
import suds.store
import suds.transport
import truststore
from PIL import Image

from pyhfc.api.quicklook import load_image, quicklook_url
from pyhfc.api.sql import (
    HQI_TFORMAT,
    DateLike,
    Where,
    and_conditions,
    check_identifier,
    hqi_where,
    nearest_date_order,
    sql_date,
    sql_quote,
    sql_where,
    to_datetime,
)
from pyhfc.api.tables import feature_table
from pyhfc.api.votable import QueryResponse, Row, VOTableError, parse_response

__all__ = [
    "HQI_DEV_WSDL",
    "HQI_WSDL",
    "RECENT_MAX_AGE",
    "RECENT_PERIOD",
    "HQIClient",
    "HQIConnectionError",
    "HQIError",
    "HQIQueryError",
    "ResponseCache",
    "response_max_age",
]

logger = logging.getLogger(__name__)

#: WSDL of the HQI of the HFC
HQI_WSDL = "http://voparis-helio.obspm.fr/hfc-hqi/HelioTavernaService?wsdl"
#: WSDL of the development version of the HQI of the HFC
HQI_DEV_WSDL = "http://voparis-helio.obspm.fr/hfc-hqi-dev/HelioTavernaService?wsdl"

#: XML schemas imported by the HQI WSDL, bundled with the package (location -> file
#: in pyhfc/api/schemas). They are not downloaded, which avoids depending on the
#: availability of their server, and on its certificate chain (www.helio-vo.eu sends
#: an incomplete chain, which can not be verified by OpenSSL).
BUNDLED_SCHEMAS = {
    "www.helio-vo.eu/services/xml/instruments.xsd": "instruments.xsd",
}


def bundled_schemas() -> suds.store.DocumentStore:
    """Return a suds document store providing the bundled XML schemas."""
    schemas = files("pyhfc.api") / "schemas"
    return suds.store.DocumentStore(
        {location: (schemas / name).read_bytes() for location, name in BUNDLED_SCHEMAS.items()}
    )


#: Responses with observations more recent than this period may still be completed
#: in the HFC (e.g. features not yet detected): they are cached for a limited time.
RECENT_PERIOD = timedelta(days=7)
#: Maximum age, in seconds, of the cached responses with recent observations
RECENT_MAX_AGE = 3600.0
#: Maximum age, in seconds, of the cached responses without dates (e.g. table names)
UNDATED_MAX_AGE = 86400.0


class ResponseCache(Protocol):
    """Cache of the responses of the service (VOTable documents)."""

    def get(self, key: str) -> bytes | None:
        """Return the cached response for a key, or None (missing or expired)."""
        ...

    def put(self, key: str, data: bytes, max_age: float | None = None) -> bool:
        """Cache a response; ``max_age`` in seconds (None: no expiration)."""
        ...


class HQIError(Exception):
    """Base class of the errors raised by the HQI client."""


class HQIConnectionError(HQIError):
    """The web service can not be reached."""


class HQIQueryError(HQIError):
    """The web service has returned an error."""

    def __init__(self, message: str, response: QueryResponse | None = None) -> None:
        super().__init__(message)
        self.response = response


def _as_list(value: str | Sequence[str]) -> list[str]:
    if isinstance(value, str):
        return [value]
    return list(value)


def _as_str(value: str | Sequence[str]) -> str:
    return value if isinstance(value, str) else ", ".join(value)


def _hqi_date(value: DateLike) -> str:
    return to_datetime(value).strftime(HQI_TFORMAT)


class HQIClient:
    """Client of the HELIO Query Interface (HQI) of the HFC.

    :param wsdl: url of the WSDL of the service (default: the HFC production service).
    :param timeout: timeout of the requests, in seconds.
    :param typed: convert the values to Python types (else keep them as strings).
    :param parse_dates: convert ISO 8601 dates to ``datetime`` (if ``typed``).
    :param soap_client: an existing ``suds`` client (created from ``wsdl`` if not given).
    :param cache: cache of the responses (see :class:`ResponseCache`); only the
        successful responses with rows are cached, the ones with recent
        observations (see :data:`RECENT_PERIOD`) for :data:`RECENT_MAX_AGE` only.

    All the query methods return a :class:`QueryResponse` and raise a
    :class:`HQIError` if the query fails.
    """

    def __init__(
        self,
        wsdl: str = HQI_WSDL,
        *,
        timeout: float = 60,
        typed: bool = True,
        parse_dates: bool = True,
        soap_client: Any = None,
        cache: ResponseCache | None = None,
    ) -> None:
        self.wsdl = wsdl
        self.timeout = timeout
        self.typed = typed
        self.parse_dates = parse_dates
        self._soap_client = soap_client
        self.cache = cache

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.wsdl!r})"

    @property
    def soap_client(self) -> Any:
        """The ``suds`` client of the web service (created on first use)."""
        if self._soap_client is None:
            # Use the OS certificate store for the HTTPS requests.
            truststore.inject_into_ssl()
            try:
                self._soap_client = suds.client.Client(
                    self.wsdl,
                    retxml=True,
                    timeout=self.timeout,
                    documentStore=bundled_schemas(),
                )
            except (suds.transport.TransportError, OSError) as err:
                raise HQIConnectionError(f"Can not reach {self.wsdl}: {err}") from err
        return self._soap_client

    # ________________ Generic call __________________

    def call(self, method: str, *, use_cache: bool = True, **params: Any) -> QueryResponse:
        """Call a method of the web service and parse its response.

        Parameters with a ``None`` value are not sent. If the client has a
        cache, the response is read from it when possible, and stored in it
        (``use_cache=False`` to always query the service).
        """
        params = {key: value for key, value in params.items() if value is not None}
        key = self.cache_key(method, params) if self.cache is not None and use_cache else None
        if key is not None and (response := self._cached_response(key)) is not None:
            logger.debug("HQI %s(%s): response read from the cache", method, params)
            return response

        service = self.soap_client.service
        if not hasattr(service, method):
            raise HQIError(f"The web service {self.wsdl} has no method {method}")
        logger.debug("HQI %s(%s)", method, params)
        try:
            xml = getattr(service, method)(**params)
        except suds.WebFault as err:
            raise HQIQueryError(f"{method} has failed: {err}") from err
        except (suds.transport.TransportError, OSError) as err:
            raise HQIConnectionError(f"Can not reach {self.wsdl}: {err}") from err
        try:
            response = parse_response(xml, typed=self.typed, parse_dates=self.parse_dates)
        except (VOTableError, SyntaxError) as err:
            raise HQIQueryError(f"Invalid response of {method}: {err}") from err
        if response.status == "ERROR":
            message = response.error or "unknown error"
            raise HQIQueryError(f"{method} has failed: {message} ({params})", response)
        logger.debug("%i row(s) returned.", len(response))
        if key is not None and self.cache is not None and response.rows:
            self.cache.put(key, response.votable, response_max_age(response))
        return response

    def cache_key(self, method: str, params: Mapping[str, Any]) -> str:
        """Key of a query in the cache: hash of the service, the method and the parameters."""
        query = json.dumps([self.wsdl, method, params], sort_keys=True, default=str)
        return hashlib.sha256(query.encode()).hexdigest()

    def _cached_response(self, key: str) -> QueryResponse | None:
        assert self.cache is not None
        data = self.cache.get(key)
        if data is None:
            return None
        try:
            response = parse_response(data, typed=self.typed, parse_dates=self.parse_dates)
        except (VOTableError, SyntaxError) as err:
            logger.warning("Invalid cached response (%s): the service is queried", err)
            return None
        return response if response.status != "ERROR" else None

    # ________________ Service methods _______________

    def tables(self) -> list[str]:
        """Return the names of the tables of the HFC."""
        return [str(row["TABLE_NAMES"]) for row in self.call("getTableNames")]

    def fields(self, table: str) -> list[str]:
        """Return the names of the fields of a table."""
        response = self.call("getTableFields", table_name=table)
        return [str(row["FIELD_NAMES"]) for row in response]

    def select(
        self,
        table: str | Sequence[str],
        what: str | Sequence[str] = "*",
        where: Where = None,
        order_by: str | Sequence[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        use_cache: bool = True,
    ) -> QueryResponse:
        """Run a SQL SELECT query (``SQLSelect`` method).

        :param table: table(s) to query (``FROM``).
        :param what: columns to return, e.g. ``"DATE_OBS, R_SUN"`` or ``["DATE_OBS", "R_SUN"]``.
        :param where: condition, as a SQL string or a mapping (see :func:`sql_where`).
        :param order_by: SQL ORDER BY clause.
        :param limit: maximum number of rows.
        :param offset: number of rows to skip.
        :param use_cache: use the cache of the client, if any.
        """
        return self.call(
            "SQLSelect",
            use_cache=use_cache,
            WHAT=_as_str(what),
            FROM=_as_list(table),
            WHERE=sql_where(where),
            ORDER_BY=_as_str(order_by) if order_by is not None else None,
            LIMIT=limit,
            OFFSET=offset,
        )

    def time_query(
        self,
        table: str | Sequence[str],
        start: DateLike,
        end: DateLike,
        max_records: int | None = None,
        start_index: int | None = None,
    ) -> QueryResponse:
        """Return the rows observed between two dates (``TimeQuery`` method)."""
        return self.call(
            "TimeQuery",
            STARTTIME=[_hqi_date(start)],
            ENDTIME=[_hqi_date(end)],
            FROM=_as_list(table),
            MAXRECORDS=max_records,
            STARTINDEX=start_index,
        )

    def query(
        self,
        table: str | Sequence[str],
        start: DateLike,
        end: DateLike,
        where: Where = None,
        max_records: int | None = None,
        start_index: int | None = None,
        join: str | None = None,
    ) -> QueryResponse:
        """Run a HQI query between two dates (``Query`` method).

        ``where`` uses the HQI syntax (see :func:`hqi_where`), e.g.
        ``{"OBSERVAT": "SDO", "FEAT_AREA_DEG2": (10, None)}`` or
        ``"OBSERVAT,SDO;FEAT_AREA_DEG2,10/"``.
        """
        return self.call(
            "Query",
            STARTTIME=[_hqi_date(start)],
            ENDTIME=[_hqi_date(end)],
            FROM=_as_list(table),
            WHERE=hqi_where(where),
            MAXRECORDS=max_records,
            STARTINDEX=start_index,
            JOIN=join,
        )

    # ________________ Helpers _______________________

    def nearest(
        self,
        table: str,
        date: DateLike,
        *,
        what: str | Sequence[str] = "*",
        where: Where = None,
        column: str = "DATE_OBS",
    ) -> Row | None:
        """Return the row of a table observed nearest to a date (None if none)."""
        response = self.select(
            table,
            what=what,
            where=where,
            order_by=nearest_date_order(date, column),
            limit=1,
        )
        return response.first()

    def previous(
        self,
        table: str,
        date: DateLike,
        *,
        what: str | Sequence[str] = "*",
        where: Where = None,
        column: str = "DATE_OBS",
    ) -> Row | None:
        """Return the last row of a table observed before a date (None if none)."""
        column = check_identifier(column)
        condition = f"({column} < {sql_quote(sql_date(date))})"
        response = self.select(
            table,
            what=what,
            where=and_conditions(sql_where(where), condition),
            order_by=f"{column} DESC",
            limit=1,
        )
        return response.first()

    def next(
        self,
        table: str,
        date: DateLike,
        *,
        what: str | Sequence[str] = "*",
        where: Where = None,
        column: str = "DATE_OBS",
    ) -> Row | None:
        """Return the first row of a table observed after a date (None if none)."""
        column = check_identifier(column)
        condition = f"({column} > {sql_quote(sql_date(date))})"
        response = self.select(
            table,
            what=what,
            where=and_conditions(sql_where(where), condition),
            order_by=f"{column} ASC",
            limit=1,
        )
        return response.first()

    def features(
        self,
        feature: str,
        start: DateLike,
        end: DateLike,
        *,
        what: str | Sequence[str] = "*",
        where: Where = None,
        order_by: str | Sequence[str] | None = "DATE_OBS",
        limit: int | None = None,
    ) -> QueryResponse:
        """Return the features (e.g. "ar", "sunspots", "filaments") observed between two dates."""
        return self.select(
            feature_table(feature),
            what=what,
            where=and_conditions(
                sql_where({"DATE_OBS": (to_datetime(start), to_datetime(end))}),
                sql_where(where),
            ),
            order_by=order_by,
            limit=limit,
        )

    def quicklook(self, row: Mapping[str, Any], timeout: float | None = None) -> Image.Image | None:
        """Load the quicklook image of a row (it needs the QCLK_URL and QCLK_FNAME fields)."""
        url = quicklook_url(row)
        if url is None:
            logger.warning("No quicklook image for this row")
            return None
        return load_image(url, timeout=timeout or self.timeout)


def response_max_age(response: QueryResponse, now: datetime | None = None) -> float | None:
    """Return how long a response can be cached, in seconds (None: no expiration).

    Responses with recent observations (DATE_OBS within :data:`RECENT_PERIOD`)
    may still be completed in the HFC, and responses without dates may change.
    """
    dates = []
    for row in response.rows:
        value = row.get("DATE_OBS")
        if value in (None, ""):
            continue
        try:
            dates.append(to_datetime(value))
        except (TypeError, ValueError):
            continue
    if not dates:
        return UNDATED_MAX_AGE
    now = now or datetime.now()
    return RECENT_MAX_AGE if max(dates) > now - RECENT_PERIOD else None
