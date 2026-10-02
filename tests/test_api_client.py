# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.error import URLError

import pytest
import suds
import suds.transport
from conftest import FakeService, make_response
from PIL import Image

from pyhfc.api import (
    FEATURE_TABLES,
    HQIClient,
    HQIConnectionError,
    HQIError,
    HQIQueryError,
    feature_table,
    load_image,
    quicklook_url,
)
from pyhfc.api import quicklook as quicklook_module
from pyhfc.api.client import (
    BUNDLED_SCHEMAS,
    RECENT_MAX_AGE,
    UNDATED_MAX_AGE,
    bundled_schemas,
    response_max_age,
)
from pyhfc.api.votable import QueryResponse, parse_response

DATE = datetime(2012, 6, 1, 12, 0, 0)
DATE_ROW = [{"DATE_OBS": "2012-06-02T07:01:45"}]


def test_select(hqi: HQIClient, fake_service: FakeService) -> None:
    fake_service.responses.append(make_response(DATE_ROW))
    response = hqi.select(
        "VIEW_AR_HQI",
        what=["DATE_OBS", "R_SUN"],
        where={"OBSERVAT": "SDO"},
        order_by="DATE_OBS",
        limit=10,
        offset=5,
    )
    assert response.first() == {"DATE_OBS": datetime(2012, 6, 2, 7, 1, 45)}
    assert fake_service.calls == [
        (
            "SQLSelect",
            {
                "WHAT": "DATE_OBS, R_SUN",
                "FROM": ["VIEW_AR_HQI"],
                "WHERE": "(OBSERVAT = 'SDO')",
                "ORDER_BY": "DATE_OBS",
                "LIMIT": 10,
                "OFFSET": 5,
            },
        )
    ]


def test_select_omits_unset_parameters(hqi: HQIClient, fake_service: FakeService) -> None:
    fake_service.responses.append(make_response(DATE_ROW))
    hqi.select("VIEW_AR_HQI")
    assert fake_service.params == [{"WHAT": "*", "FROM": ["VIEW_AR_HQI"]}]


def test_client_untyped(fake_service: FakeService) -> None:
    fake_service.responses.append(make_response(DATE_ROW))
    assert HQIClient(typed=False).select("T").rows == DATE_ROW


def test_query_error(hqi: HQIClient, fake_service: FakeService) -> None:
    fake_service.responses.append(make_response(status="ERROR", error="Bad SQL"))
    with pytest.raises(HQIQueryError, match="Bad SQL") as excinfo:
        hqi.select("NOPE")
    assert excinfo.value.response is not None
    assert excinfo.value.response.status == "ERROR"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (suds.transport.TransportError("down", 503), HQIConnectionError),
        (OSError("unreachable"), HQIConnectionError),
        (suds.WebFault("fault", None), HQIQueryError),
    ],
)
def test_call_errors(
    hqi: HQIClient, fake_service: FakeService, error: Exception, expected: type[HQIError]
) -> None:
    fake_service.responses.append(error)
    with pytest.raises(expected):
        hqi.select("VIEW_AR_HQI")


def test_invalid_response(hqi: HQIClient, fake_service: FakeService) -> None:
    fake_service.responses.append(b"not xml")
    with pytest.raises(HQIQueryError, match="Invalid response"):
        hqi.select("VIEW_AR_HQI")


def test_unknown_method(hqi: HQIClient) -> None:
    with pytest.raises(HQIError, match="no method"):
        hqi.call("Unknown")


def test_errors_hierarchy() -> None:
    assert issubclass(HQIConnectionError, HQIError)
    assert issubclass(HQIQueryError, HQIError)


def test_tables_and_fields(hqi: HQIClient, fake_service: FakeService) -> None:
    fake_service.responses += [
        make_response([{"TABLE_NAMES": "VIEW_AR_HQI"}, {"TABLE_NAMES": "VIEW_SP_HQI"}]),
        make_response([{"FIELD_NAMES": "DATE_OBS"}, {"FIELD_NAMES": "R_SUN"}]),
    ]
    assert hqi.tables() == ["VIEW_AR_HQI", "VIEW_SP_HQI"]
    assert hqi.fields("VIEW_AR_HQI") == ["DATE_OBS", "R_SUN"]
    assert fake_service.calls == [
        ("getTableNames", {}),
        ("getTableFields", {"table_name": "VIEW_AR_HQI"}),
    ]


def test_time_query(hqi: HQIClient, fake_service: FakeService) -> None:
    fake_service.responses.append(make_response(DATE_ROW))
    hqi.time_query(["VIEW_AR_HQI", "VIEW_SP_HQI"], DATE, "2012-06-01 13:00:00", max_records=5)
    assert fake_service.calls == [
        (
            "TimeQuery",
            {
                "STARTTIME": ["2012-06-01T12:00:00"],
                "ENDTIME": ["2012-06-01T13:00:00"],
                "FROM": ["VIEW_AR_HQI", "VIEW_SP_HQI"],
                "MAXRECORDS": 5,
            },
        )
    ]


def test_query(hqi: HQIClient, fake_service: FakeService) -> None:
    fake_service.responses.append(make_response(DATE_ROW))
    hqi.query(
        "VIEW_AR_HQI",
        "2012-06-01",
        "2012-06-02",
        where={"OBSERVAT": "SDO", "FEAT_AREA_DEG2": (10, None)},
        start_index=2,
    )
    assert fake_service.calls == [
        (
            "Query",
            {
                "STARTTIME": ["2012-06-01T00:00:00"],
                "ENDTIME": ["2012-06-02T00:00:00"],
                "FROM": ["VIEW_AR_HQI"],
                "WHERE": "OBSERVAT,SDO;FEAT_AREA_DEG2,10/",
                "STARTINDEX": 2,
            },
        )
    ]


def test_nearest(hqi: HQIClient, fake_service: FakeService) -> None:
    fake_service.responses.append(make_response(DATE_ROW))
    row = hqi.nearest("VIEW_PP_HQI", DATE, what="DATE_OBS", where="(WAVENAME = 'Halpha')")
    assert row == {"DATE_OBS": datetime(2012, 6, 2, 7, 1, 45)}
    assert fake_service.params == [
        {
            "WHAT": "DATE_OBS",
            "FROM": ["VIEW_PP_HQI"],
            "WHERE": "(WAVENAME = 'Halpha')",
            "ORDER_BY": "ABS(EXTRACT(EPOCH FROM (DATE_OBS - TIMESTAMP '2012-06-01 12:00:00')))",
            "LIMIT": 1,
        }
    ]


def test_previous_and_next(hqi: HQIClient, fake_service: FakeService) -> None:
    fake_service.responses += [make_response(DATE_ROW), make_response([], [("DATE_OBS", "char")])]
    assert hqi.previous("T", DATE, where={"OBSERVAT": "SDO"}) is not None
    assert hqi.next("T", DATE) is None
    previous, following = fake_service.params
    assert previous["WHERE"] == ("((OBSERVAT = 'SDO')) AND ((DATE_OBS < '2012-06-01 12:00:00'))")
    assert previous["ORDER_BY"] == "DATE_OBS DESC"
    assert previous["LIMIT"] == 1
    assert following["WHERE"] == "(DATE_OBS > '2012-06-01 12:00:00')"
    assert following["ORDER_BY"] == "DATE_OBS ASC"


def test_features(hqi: HQIClient, fake_service: FakeService) -> None:
    fake_service.responses.append(make_response(DATE_ROW))
    hqi.features("Sunspots", DATE, "2012-06-01T13:00:00", where={"OBSERVAT": "SDO"}, limit=3)
    assert fake_service.params == [
        {
            "WHAT": "*",
            "FROM": ["VIEW_SP_HQI"],
            "WHERE": (
                "((DATE_OBS BETWEEN '2012-06-01 12:00:00' AND '2012-06-01 13:00:00'))"
                " AND ((OBSERVAT = 'SDO'))"
            ),
            "ORDER_BY": "DATE_OBS",
            "LIMIT": 3,
        }
    ]


@pytest.mark.parametrize(
    ("feature", "table"),
    [
        ("AR", "VIEW_AR_HQI"),
        ("active regions", "VIEW_AR_HQI"),
        ("Coronal-Holes", "VIEW_CH_HQI"),
        ("sunspots", "VIEW_SP_HQI"),
        ("sp", "VIEW_SP_HQI"),
        ("filament", "VIEW_FIL_HQI"),
        ("prominences", "VIEW_PRO_HQI"),
        ("rs", "VIEW_RS_HQI"),
        ("type_iii", "VIEW_T3_HQI"),
        ("t2", "VIEW_T2_HQI"),
    ],
)
def test_feature_table(feature: str, table: str) -> None:
    assert feature_table(feature) == table
    assert table in FEATURE_TABLES.values()


def test_feature_table_unknown() -> None:
    with pytest.raises(KeyError, match="Unknown feature"):
        feature_table("unknown")


def test_soap_client_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise suds.transport.TransportError("down", 503)

    monkeypatch.setattr("suds.client.Client", fail)
    with pytest.raises(HQIConnectionError):
        HQIClient("http://example.org/wsdl").soap_client  # noqa: B018 - property access


def test_repr() -> None:
    assert repr(HQIClient("http://example.org/wsdl")) == "HQIClient('http://example.org/wsdl')"


# ________________ Quicklook images _____________


def test_quicklook_url() -> None:
    row = {"QCLK_URL": "ftp://example.org/qclk/", "QCLK_FNAME": "image.png"}
    assert quicklook_url(row) == "ftp://example.org/qclk/image.png"
    assert quicklook_url({"QCLK_URL": "", "QCLK_FNAME": "image.png"}) is None


def test_load_image_local(tmp_path: Path) -> None:
    path = tmp_path / "image.png"
    Image.new("L", (4, 3)).save(path)
    image = load_image(path)
    assert image is not None
    assert image.size == (4, 3)


def test_load_image_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert load_image(tmp_path / "missing.png") is None
    (tmp_path / "bad.png").write_text("not an image")
    assert load_image(tmp_path / "bad.png") is None

    def fail(*args: object, **kwargs: object) -> None:
        raise URLError("unreachable")

    monkeypatch.setattr(quicklook_module, "urlopen", fail)
    assert load_image("ftp://example.org/image.png") is None


def test_client_quicklook(hqi: HQIClient, tmp_path: Path) -> None:
    Image.new("L", (4, 3)).save(tmp_path / "image.png")
    assert hqi.quicklook({"QCLK_URL": str(tmp_path), "QCLK_FNAME": "image.png"}) is not None
    assert hqi.quicklook({"DATE_OBS": "2012-06-01T12:00:00"}) is None


def test_bundled_schemas() -> None:
    store = bundled_schemas()
    for location in BUNDLED_SCHEMAS:
        content = store.open(f"http://{location}")
        assert content is not None
        assert b"<xs:schema" in content


# ________________ Response cache ________________


class MemoryCache:
    """Response cache in memory, recording the maximum ages."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.max_ages: dict[str, float | None] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def put(self, key: str, data: bytes, max_age: float | None = None) -> bool:
        self.data[key] = data
        self.max_ages[key] = max_age
        return True


def test_cache_avoids_queries(fake_service: FakeService) -> None:
    memory = MemoryCache()
    hqi = HQIClient(cache=memory)
    fake_service.responses.append(make_response(DATE_ROW))
    first = hqi.select("VIEW_AR_HQI", what="DATE_OBS", limit=1)
    second = hqi.select("VIEW_AR_HQI", what="DATE_OBS", limit=1)
    assert len(fake_service.calls) == 1
    assert second.rows == first.rows
    assert second.votable == first.votable
    # an old observation: cached without expiration
    assert list(memory.max_ages.values()) == [None]


def test_cache_hit_does_not_need_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    memory = MemoryCache()
    hqi = HQIClient(cache=memory)
    key = hqi.cache_key("SQLSelect", {"WHAT": "*", "FROM": ["T"]})
    memory.data[key] = make_response(DATE_ROW, envelope=False)

    def no_service(self: HQIClient) -> None:
        raise AssertionError("the service must not be reached")

    monkeypatch.setattr(HQIClient, "soap_client", property(no_service))
    assert hqi.select("T").first() == {"DATE_OBS": datetime(2012, 6, 2, 7, 1, 45)}


def test_cache_untyped_client(fake_service: FakeService) -> None:
    memory = MemoryCache()
    fake_service.responses.append(make_response(DATE_ROW))
    HQIClient(cache=memory).select("T")
    # the cached VOTable is converted according to the client settings
    assert HQIClient(cache=memory, typed=False).select("T").rows == DATE_ROW


def test_cache_skips_empty_and_error_responses(fake_service: FakeService) -> None:
    memory = MemoryCache()
    hqi = HQIClient(cache=memory)
    fake_service.responses += [
        make_response([], [("DATE_OBS", "char")]),
        make_response(status="ERROR", error="Bad SQL"),
        make_response(DATE_ROW),
    ]
    assert not hqi.select("T")
    with pytest.raises(HQIQueryError):
        hqi.select("NOPE")
    assert memory.data == {}
    # the empty response was not cached: the service is queried again
    assert hqi.select("T").rows
    assert len(fake_service.calls) == 3


def test_cache_disabled_for_a_query(fake_service: FakeService) -> None:
    memory = MemoryCache()
    hqi = HQIClient(cache=memory)
    fake_service.responses += [make_response(DATE_ROW), make_response(DATE_ROW)]
    hqi.select("T", use_cache=False)
    hqi.select("T", use_cache=False)
    assert len(fake_service.calls) == 2
    assert memory.data == {}


def test_cache_key() -> None:
    hqi = HQIClient()
    key = hqi.cache_key("SQLSelect", {"FROM": ["T"], "WHAT": "*"})
    assert key == hqi.cache_key("SQLSelect", {"WHAT": "*", "FROM": ["T"]})
    assert key != hqi.cache_key("SQLSelect", {"WHAT": "*", "FROM": ["U"]})
    assert key != HQIClient("http://other/wsdl").cache_key(
        "SQLSelect", {"WHAT": "*", "FROM": ["T"]}
    )


def test_response_max_age() -> None:
    now = datetime(2026, 10, 2, 12, 0, 0)

    def response(*dates: str) -> QueryResponse:
        rows = [{"DATE_OBS": d} for d in dates]
        return parse_response(make_response(rows, [("DATE_OBS", "char")]))

    assert response_max_age(response("2012-06-01T12:00:00"), now) is None
    assert response_max_age(response("2026-09-30T08:00:00"), now) == RECENT_MAX_AGE
    # the most recent observation decides
    assert response_max_age(response("2012-06-01T12:00:00", "2026-10-02T07:59:33"), now) == (
        RECENT_MAX_AGE
    )
    tables = parse_response(make_response([{"TABLE_NAMES": "VIEW_AR_HQI"}]))
    assert response_max_age(tables, now) == UNDATED_MAX_AGE
