# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from conftest import FieldSpec, make_response, make_table_xml

from pyhfc.api.votable import Field, VOTableError, extract_votable, parse_response

FIELDS: list[FieldSpec] = [
    ("DATE_OBS", "char"),
    ("JDINT", "int", "-2147483648"),
    ("R_SUN", "double"),
    ("CC", "char"),
]
ROWS = [
    {"DATE_OBS": "2012-06-01T12:00:00", "JDINT": 2456080, "R_SUN": 485.5, "CC": "0123"},
    {"DATE_OBS": "2012-06-02T07:01:45", "JDINT": -2147483648, "R_SUN": None, "CC": None},
]


@pytest.mark.parametrize("envelope", [True, False])
def test_parse_response_typed(envelope: bool) -> None:
    response = parse_response(make_response(ROWS, FIELDS, table="VIEW_AR_HQI", envelope=envelope))
    assert response.status == "OK"
    assert response.error is None
    assert response.query_string == "SELECT * FROM VIEW_AR_HQI"
    assert response.description == "HFC Query Interface"
    assert [t.name for t in response.tables] == ["VIEW_AR_HQI"]
    assert [f.name for f in response.fields] == ["DATE_OBS", "JDINT", "R_SUN", "CC"]
    assert response.fields[1] == Field("JDINT", "int", null="-2147483648")
    assert response.rows == [
        {"DATE_OBS": datetime(2012, 6, 1, 12), "JDINT": 2456080, "R_SUN": 485.5, "CC": "0123"},
        {"DATE_OBS": datetime(2012, 6, 2, 7, 1, 45), "JDINT": None, "R_SUN": None, "CC": ""},
    ]
    assert len(response) == 2
    assert response[1]["JDINT"] is None
    assert response.first() == response.rows[0]
    assert response.tables[0].column("r_sun") == [485.5, None]


def test_parse_response_untyped() -> None:
    response = parse_response(make_response(ROWS, FIELDS), typed=False)
    assert response.rows[0] == {
        "DATE_OBS": "2012-06-01T12:00:00",
        "JDINT": "2456080",
        "R_SUN": "485.5",
        "CC": "0123",
    }
    assert response.rows[1]["JDINT"] == "-2147483648"
    assert response.rows[1]["R_SUN"] == ""


def test_parse_response_without_dates() -> None:
    response = parse_response(make_response(ROWS, FIELDS), parse_dates=False)
    assert response.rows[0]["DATE_OBS"] == "2012-06-01T12:00:00"
    assert response.rows[0]["JDINT"] == 2456080


@pytest.mark.parametrize(
    ("datatype", "text", "value"),
    [
        ("short", "12", 12),
        ("long", "", None),
        ("float", "1e3", 1000.0),
        ("int", "abc", "abc"),
        ("boolean", "T", True),
        ("boolean", "false", False),
        ("char", " A ", "A"),
    ],
)
def test_field_convert(datatype: str, text: str, value: object) -> None:
    assert Field("X", datatype).convert(text) == value


def test_parse_response_empty() -> None:
    response = parse_response(make_response([], [("DATE_OBS", "char")]))
    assert response.rows == []
    assert response.first() is None
    assert not response


def test_parse_response_error() -> None:
    response = parse_response(make_response(status="ERROR", error="Bad SQL"))
    assert response.status == "ERROR"
    assert response.error == "Bad SQL"
    assert response.tables == []


def test_parse_response_several_tables() -> None:
    tables = [
        make_table_xml("VIEW_AR_HQI", [{"ID": "1"}, {"ID": "2"}]),
        make_table_xml("VIEW_SP_HQI", [{"ID": "3"}]),
    ]
    response = parse_response(make_response(tables=tables))
    assert [t.name for t in response.tables] == ["VIEW_AR_HQI", "VIEW_SP_HQI"]
    assert [row["ID"] for row in response] == ["1", "2", "3"]
    assert len(response.table("view_sp_hqi")) == 1
    with pytest.raises(KeyError):
        response.table("VIEW_CH_HQI")


def test_to_dict() -> None:
    response = parse_response(make_response(ROWS, FIELDS, table="VIEW_AR_HQI"), typed=False)
    data = response.to_dict()
    assert data["description"] == "HFC Query Interface"
    assert data["info"]["QUERY_STATUS"] == "OK"
    (table,) = data["tables"]
    assert table["name"] == "VIEW_AR_HQI"
    assert table["fields"][1] == {
        "name": "JDINT",
        "datatype": "int",
        "arraysize": None,
        "ucd": None,
        "utype": None,
        "unit": None,
        "null": "-2147483648",
    }
    assert table["rows"] == response.rows
    # the dictionary is a copy
    table["rows"][0]["CC"] = "changed"
    assert response.rows[0]["CC"] == "0123"


def test_legacy_header_and_tabledata() -> None:
    response = parse_response(make_response(ROWS, FIELDS), typed=False)
    header = response.header
    assert header["DESCRIPTION"] == "HFC Query Interface"
    assert {"NAME": "QUERY_STATUS", "VALUE": "OK"} in header["INFO"]
    assert header["FIELD"][0] == {"NAME": "DATE_OBS", "DATATYPE": "char", "ARRAYSIZE": "*"}
    assert response.tabledata == response.rows


def test_votable_document(tmp_path: Path) -> None:
    response = parse_response(make_response(ROWS, FIELDS))
    assert response.votable.startswith(b"<?xml")
    assert b"Envelope" not in response.votable
    assert b'xmlns="http://www.ivoa.net/xml/VOTable/v1.1"' in response.votable
    # the VOTable document can be parsed again
    assert parse_response(response.votable).rows == response.rows

    path = tmp_path / "result.xml"
    response.save(path)
    assert path.read_bytes() == response.votable


def test_extract_votable_errors() -> None:
    fault = (
        b'<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/"><S:Body>'
        b"<S:Fault><faultcode>S:Server</faultcode><faultstring>Boom</faultstring></S:Fault>"
        b"</S:Body></S:Envelope>"
    )
    with pytest.raises(VOTableError, match="Boom"):
        extract_votable(fault)
    with pytest.raises(VOTableError, match="No VOTABLE"):
        extract_votable(b"<root />")


def test_to_pandas() -> None:
    pytest.importorskip("pandas")
    frame = parse_response(make_response(ROWS, FIELDS)).to_pandas()
    assert list(frame.columns) == ["DATE_OBS", "JDINT", "R_SUN", "CC"]
    assert frame["R_SUN"].iloc[0] == 485.5


def test_to_astropy() -> None:
    pytest.importorskip("astropy")
    table = parse_response(make_response(ROWS, FIELDS)).to_astropy()
    assert table.colnames == ["date_obs", "jdint", "r_sun", "cc"]
    assert table["jdint"][0] == 2456080
    assert table["jdint"].mask[1]
