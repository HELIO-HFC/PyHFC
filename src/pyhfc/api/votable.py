# SPDX-License-Identifier: EUPL-1.2
"""Parsing of the VOTables returned by the HELIO Query Interface (HQI).

The HQI web service returns a VOTable (v1.1) document wrapped in a SOAP
envelope. :func:`parse_response` extracts this VOTable, and converts it to a
:class:`QueryResponse`, giving access to:

- the original VOTable document (:attr:`QueryResponse.votable`), which can be
  saved or read with any VO tool (e.g. ``astropy.io.votable``);
- the rows of each table, as dictionaries of (typed) Python values;
- the whole VOTable as a dictionary (:meth:`QueryResponse.to_dict`).
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas
    from astropy.table import Table as AstropyTable

__all__ = ["Field", "QueryResponse", "Row", "Table", "extract_votable", "parse_response"]

#: A row of a table: {FIELD_NAME: value}
Row = dict[str, Any]

_INT_TYPES = {"short", "int", "long", "unsignedByte"}
_FLOAT_TYPES = {"float", "double"}
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?$")


def _local(tag: str) -> str:
    """Return the tag name without its namespace."""
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _local(child.tag) == name]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    children = _children(element, name)
    return children[0] if children else None


@dataclass(frozen=True)
class Field:
    """Description of a column (VOTable FIELD)."""

    name: str
    datatype: str = "char"
    arraysize: str | None = None
    ucd: str | None = None
    utype: str | None = None
    unit: str | None = None
    null: str | None = None

    def convert(self, text: str | None, typed: bool = True, parse_dates: bool = True) -> Any:
        """Convert the text of a cell to a Python value.

        If ``typed`` is false, the text is returned as is (``""`` if empty).
        Otherwise, null values give ``None``; numbers are converted according
        to the FIELD datatype; ISO 8601 dates are converted to ``datetime`` if
        ``parse_dates`` is true.
        """
        if not typed:
            return text if text is not None else ""
        if text is None:
            return None if self.datatype != "char" else ""
        text = text.strip()
        if self.null is not None and text == self.null:
            return None
        try:
            if self.datatype in _INT_TYPES:
                return int(text) if text else None
            if self.datatype in _FLOAT_TYPES:
                return float(text) if text else None
        except ValueError:
            return text
        if self.datatype == "boolean":
            return text.lower() in ("t", "true", "1") if text else None
        if parse_dates and _DATE_PATTERN.match(text):
            return datetime.fromisoformat(text)
        return text


@dataclass
class Table:
    """A table of a query response."""

    name: str
    fields: list[Field] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def column(self, name: str) -> list[Any]:
        """Return the values of a column."""
        name = name.upper()
        return [row.get(name) for row in self.rows]

    def to_dict(self) -> dict[str, Any]:
        """Return the table as a dictionary {"name", "fields", "rows"}."""
        return {
            "name": self.name,
            "fields": [asdict(f) for f in self.fields],
            "rows": [dict(row) for row in self.rows],
        }

    def to_pandas(self) -> pandas.DataFrame:
        """Convert the table to a pandas DataFrame (requires pandas)."""
        import pandas  # optional dependency

        return pandas.DataFrame(self.rows, columns=self.field_names)

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[Row]:
        return iter(self.rows)

    def __getitem__(self, index: int) -> Row:
        return self.rows[index]


@dataclass
class QueryResponse:
    """Response of a HQI query.

    Iterating on a response, or using ``len()`` and indexing, works on
    :attr:`rows`, i.e. the rows of all the tables.
    """

    votable: bytes
    tables: list[Table] = field(default_factory=list)
    info: dict[str, str] = field(default_factory=dict)
    description: str | None = None

    @property
    def status(self) -> str | None:
        """Value of the QUERY_STATUS info (``OK`` or ``ERROR``)."""
        return self.info.get("QUERY_STATUS")

    @property
    def error(self) -> str | None:
        """Error message returned by the service, if any."""
        return self.info.get("QUERY_ERROR")

    @property
    def query_string(self) -> str | None:
        """Query executed by the service (as reported by the service)."""
        return self.info.get("QUERY_STRING")

    @property
    def rows(self) -> list[Row]:
        """Rows of all the tables."""
        if len(self.tables) == 1:
            return self.tables[0].rows
        return [row for table in self.tables for row in table.rows]

    @property
    def fields(self) -> list[Field]:
        """Fields of the first table."""
        return self.tables[0].fields if self.tables else []

    def table(self, name: str) -> Table:
        """Return a table by name (e.g. ``VIEW_AR_HQI``)."""
        for table in self.tables:
            if table.name.upper() == name.upper():
                return table
        raise KeyError(name)

    def first(self) -> Row | None:
        """Return the first row, or None if there is none."""
        rows = self.rows
        return rows[0] if rows else None

    def to_dict(self) -> dict[str, Any]:
        """Return the whole VOTable as a dictionary.

        ``{"description": str, "info": {NAME: VALUE}, "tables": [{"name": str,
        "fields": [{"name", "datatype", ...}], "rows": [{FIELD: value}]}]}``
        """
        return {
            "description": self.description,
            "info": dict(self.info),
            "tables": [table.to_dict() for table in self.tables],
        }

    @property
    def header(self) -> dict[str, Any]:
        """Header of the VOTable, as returned by the former client.

        ``{"DESCRIPTION": str, "INFO": [{"NAME", "VALUE"}], "FIELD": [{"NAME",
        "DATATYPE", ...}]}``, FIELD describing the first table.
        """
        return {
            "DESCRIPTION": self.description,
            "INFO": [{"NAME": name, "VALUE": value} for name, value in self.info.items()],
            "FIELD": [
                {key.upper(): value for key, value in asdict(f).items() if value is not None}
                for f in self.fields
            ],
        }

    @property
    def tabledata(self) -> list[Row]:
        """Rows as returned by the former client (alias of :attr:`rows`)."""
        return self.rows

    def save(self, path: str | Path) -> None:
        """Save the VOTable document to a file."""
        Path(path).write_bytes(self.votable)

    def to_pandas(self) -> pandas.DataFrame:
        """Convert the rows to a pandas DataFrame (requires pandas)."""
        import pandas  # optional dependency

        if len(self.tables) == 1:
            return self.tables[0].to_pandas()
        return pandas.DataFrame(self.rows)

    def to_astropy(self, table: int = 0) -> AstropyTable:
        """Convert a table of the VOTable to an astropy Table (requires astropy)."""
        from astropy.io.votable import parse  # optional dependency

        votable = parse(io.BytesIO(self.votable), verify="ignore")
        return votable.get_table_by_index(table).to_table()

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[Row]:
        return iter(self.rows)

    def __getitem__(self, index: int) -> Row:
        return self.rows[index]


def _find_votable(root: ET.Element) -> ET.Element | None:
    if _local(root.tag) == "VOTABLE":
        return root
    return next((el for el in root.iter() if _local(el.tag) == "VOTABLE"), None)


def _soap_fault(root: ET.Element) -> str | None:
    fault = next((el for el in root.iter() if _local(el.tag) == "Fault"), None)
    if fault is None:
        return None
    message = next((el.text for el in fault.iter() if _local(el.tag) == "faultstring"), None)
    return message or "SOAP fault"


class VOTableError(ValueError):
    """The response of the service can not be parsed."""


def extract_votable(xml: bytes | str) -> bytes:
    """Extract the VOTable document from a SOAP response."""
    root = ET.fromstring(xml)
    fault = _soap_fault(root)
    if fault is not None:
        raise VOTableError(fault)
    votable = _find_votable(root)
    if votable is None:
        raise VOTableError("No VOTABLE found in the response")
    if votable.tag.startswith("{"):
        # keep the VOTable namespace as the default one
        ET.register_namespace("", votable.tag[1:].split("}")[0])
    return bytes(ET.tostring(votable, encoding="utf-8", xml_declaration=True))


def _parse_field(element: ET.Element) -> Field:
    values = _child(element, "VALUES")
    return Field(
        name=element.get("name", "").upper(),
        datatype=element.get("datatype", "char"),
        arraysize=element.get("arraysize"),
        ucd=element.get("ucd"),
        utype=element.get("utype"),
        unit=element.get("unit"),
        null=values.get("null") if values is not None else None,
    )


def _parse_table(element: ET.Element, typed: bool, parse_dates: bool) -> Table:
    name = element.get("name", "")
    name = name.removeprefix("hqi-")
    fields = [_parse_field(el) for el in _children(element, "FIELD")]
    rows: list[Row] = []
    for tr in element.iter():
        if _local(tr.tag) != "TR":
            continue
        cells = _children(tr, "TD")
        rows.append(
            {
                fld.name: fld.convert(td.text, typed, parse_dates)
                for fld, td in zip(fields, cells, strict=False)
            }
        )
    return Table(name=name, fields=fields, rows=rows)


def parse_response(xml: bytes | str, typed: bool = True, parse_dates: bool = True) -> QueryResponse:
    """Parse a HQI response (SOAP envelope or VOTable document).

    Field names are upper-cased, so that ``DATE_OBS`` works whatever the case
    used by the database backend. Values are converted to Python types if
    ``typed`` is true (see :meth:`Field.convert`), else they are kept as strings.
    """
    votable_xml = extract_votable(xml)
    root = ET.fromstring(votable_xml)
    response = QueryResponse(votable=votable_xml)
    for resource in _children(root, "RESOURCE"):
        description = _child(resource, "DESCRIPTION")
        if description is not None and response.description is None:
            response.description = (description.text or "").strip()
        for info in _children(resource, "INFO"):
            name = info.get("name")
            if name is None:
                continue
            value = info.get("value")
            if value is None:
                value = (info.text or "").strip()
            response.info.setdefault(name, value)
        response.tables.extend(
            _parse_table(t, typed, parse_dates) for t in _children(resource, "TABLE")
        )
    return response
