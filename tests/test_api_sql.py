# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from pyhfc.api import sql

DATE = datetime(2012, 6, 1, 12, 0, 0)


@pytest.mark.parametrize(
    "value",
    [DATE, "2012-06-01T12:00:00", "2012-06-01 12:00:00", " 2012-06-01T12:00:00 "],
)
def test_to_datetime(value: Any) -> None:
    assert sql.to_datetime(value) == DATE


def test_to_datetime_date() -> None:
    assert sql.to_datetime(date(2012, 6, 1)) == datetime(2012, 6, 1)


def test_quote_and_literals() -> None:
    assert sql.sql_date("2012-06-01T12:00:00") == "2012-06-01 12:00:00"
    assert sql.sql_quote("O'Brien") == "'O''Brien'"
    assert sql.sql_literal(None) == "NULL"
    assert sql.sql_literal(True) == "TRUE"
    assert sql.sql_literal(12) == "12"
    assert sql.sql_literal(1.5) == "1.5"
    assert sql.sql_literal(DATE) == "'2012-06-01 12:00:00'"
    assert sql.sql_literal("SDO") == "'SDO'"


def test_sql_equals_is_case_insensitive() -> None:
    assert sql.sql_equals("OBSERVAT", "Meudon") == "(UPPER(OBSERVAT) = 'MEUDON')"


def test_nearest_date_order_uses_postgresql_syntax() -> None:
    assert sql.nearest_date_order(DATE) == (
        "ABS(EXTRACT(EPOCH FROM (DATE_OBS - TIMESTAMP '2012-06-01 12:00:00')))"
    )
    assert "DATE_END" in sql.nearest_date_order(DATE, column="DATE_END")


@pytest.mark.parametrize(
    ("where", "expected"),
    [
        (None, None),
        ("", None),
        ("R_SUN > 10", "R_SUN > 10"),
        ({"OBSERVAT": "SDO"}, "(OBSERVAT = 'SDO')"),
        ({"NOAA_NUMBER": 11494}, "(NOAA_NUMBER = 11494)"),
        ({"NOAA_NUMBER": None}, "(NOAA_NUMBER IS NULL)"),
        ({"AREA": (10, 20)}, "(AREA BETWEEN 10 AND 20)"),
        ({"AREA": (10, None)}, "(AREA >= 10)"),
        ({"AREA": (None, 20.5)}, "(AREA <= 20.5)"),
        ({"OBSERVAT": ["SDO", "SOHO"]}, "(OBSERVAT IN ('SDO', 'SOHO'))"),
        (
            {"DATE_OBS": (DATE, "2012-06-02")},
            "(DATE_OBS BETWEEN '2012-06-01 12:00:00' AND '2012-06-02')",
        ),
        ({"OBSERVAT": "SDO", "AREA": (10, None)}, "((OBSERVAT = 'SDO')) AND ((AREA >= 10))"),
    ],
)
def test_sql_where(where: sql.Where, expected: str | None) -> None:
    assert sql.sql_where(where) == expected


@pytest.mark.parametrize(
    "where",
    [
        {"OBSERVAT; DROP TABLE": "SDO"},
        {"AREA": (1, 2, 3)},
        {"AREA": (None, None)},
        {"OBSERVAT": []},
    ],
)
def test_sql_where_invalid(where: sql.Where) -> None:
    with pytest.raises(ValueError):
        sql.sql_where(where)


def test_and_conditions_keeps_precedence() -> None:
    assert sql.and_conditions(None, "A OR B", "", "C") == "(A OR B) AND (C)"
    assert sql.and_conditions("A") == "A"
    assert sql.and_conditions(None, "") is None


@pytest.mark.parametrize(
    ("where", "expected"),
    [
        (None, None),
        ("OBSERVAT,SDO", "OBSERVAT,SDO"),
        ({"OBSERVAT": "SDO"}, "OBSERVAT,SDO"),
        ({"AREA": (10, None)}, "AREA,10/"),
        ({"AREA": (None, 5)}, "AREA,/5"),
        ({"OBSERVAT": ["SDO", "SOHO"], "AREA": (10, 20)}, "OBSERVAT,SDO,SOHO;AREA,10/20"),
        ({"DATE_OBS": (DATE, None)}, "DATE_OBS,2012-06-01T12:00:00/"),
    ],
)
def test_hqi_where(where: sql.Where, expected: str | None) -> None:
    assert sql.hqi_where(where) == expected


def test_hqi_where_invalid() -> None:
    with pytest.raises(ValueError):
        sql.hqi_where({"bad name": 1})
