# SPDX-License-Identifier: EUPL-1.2
"""Helpers to build the conditions of the HQI queries.

Two syntaxes are used by the HELIO Query Interface (HQI):

- the ``SQLSelect`` method takes SQL fragments, run on the PostgreSQL database
  of the HFC (single-quoted string literals, case-sensitive comparisons...);
- the ``Query`` method takes a HQI ``WHERE`` string: ``FIELD,value`` (equality),
  ``FIELD,min/max`` (range, one bound may be empty), ``FIELD,v1,v2`` (one of the
  values), several conditions being separated by ``;``.

Both can be built from a mapping ``{field: condition}``, see :func:`sql_where`
and :func:`hqi_where`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

__all__ = [
    "HQI_TFORMAT",
    "SQL_TFORMAT",
    "Where",
    "and_conditions",
    "hqi_where",
    "nearest_date_order",
    "sql_date",
    "sql_equals",
    "sql_literal",
    "sql_quote",
    "sql_where",
    "to_datetime",
]

SQL_TFORMAT = "%Y-%m-%d %H:%M:%S"
HQI_TFORMAT = "%Y-%m-%dT%H:%M:%S"

#: A condition: raw string, or mapping {field: value | (min, max) | [v1, v2...] | None}
Where = str | Mapping[str, Any] | None

DateLike = datetime | date | str

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def to_datetime(value: DateLike) -> datetime:
    """Convert a date (``datetime``, ``date`` or ISO 8601 string) to a datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    return datetime.fromisoformat(value.strip())


def sql_date(value: DateLike) -> str:
    """Format a date as expected by the HFC database."""
    return to_datetime(value).strftime(SQL_TFORMAT)


def sql_quote(value: str) -> str:
    """Return ``value`` as a single-quoted SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def sql_literal(value: Any) -> str:
    """Return the SQL literal of a Python value."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, datetime | date):
        return sql_quote(sql_date(value))
    return sql_quote(str(value))


def check_identifier(name: str) -> str:
    """Check that ``name`` is a valid column name, to avoid SQL injections."""
    if not _IDENTIFIER.match(name):
        raise ValueError(f"Invalid field name: {name!r}")
    return name


def sql_equals(column: str, value: str) -> str:
    """Case-insensitive equality test between a column and a string value."""
    return f"(UPPER({check_identifier(column)}) = {sql_quote(value.upper())})"


def nearest_date_order(value: DateLike, column: str = "DATE_OBS") -> str:
    """ORDER BY clause sorting rows by time distance to a date."""
    column = check_identifier(column)
    timestamp = sql_quote(sql_date(value))
    return f"ABS(EXTRACT(EPOCH FROM ({column} - TIMESTAMP {timestamp})))"


def _sql_condition(column: str, value: Any) -> str:
    column = check_identifier(column)
    if value is None:
        return f"({column} IS NULL)"
    if isinstance(value, tuple):
        if len(value) != 2:
            raise ValueError(f"A range must be a (min, max) tuple, got {value!r}")
        low, high = value
        if low is not None and high is not None:
            return f"({column} BETWEEN {sql_literal(low)} AND {sql_literal(high)})"
        if low is not None:
            return f"({column} >= {sql_literal(low)})"
        if high is not None:
            return f"({column} <= {sql_literal(high)})"
        raise ValueError(f"Empty range for {column}")
    if isinstance(value, list | set | frozenset):
        if not value:
            raise ValueError(f"Empty list of values for {column}")
        values = ", ".join(sql_literal(v) for v in value)
        return f"({column} IN ({values}))"
    return f"({column} = {sql_literal(value)})"


def sql_where(where: Where) -> str | None:
    """Build a SQL condition.

    ``where`` is either a raw SQL string, or a mapping ``{field: condition}``
    where each condition is:

    - a value: ``FIELD = value``;
    - a ``(min, max)`` tuple: ``FIELD BETWEEN min AND max`` (a bound may be ``None``);
    - a list or a set: ``FIELD IN (...)``;
    - ``None``: ``FIELD IS NULL``.

    Conditions of a mapping are combined with ``AND``.
    """
    if where is None:
        return None
    if isinstance(where, str):
        return where.strip() or None
    return and_conditions(*(_sql_condition(col, val) for col, val in where.items()))


def and_conditions(*conditions: str | None) -> str | None:
    """Combine SQL conditions with AND, ignoring the empty ones."""
    parts = [c for c in conditions if c]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    # Each part is parenthesized, e.g. to keep "A OR B" as a whole
    return " AND ".join(f"({p})" for p in parts)


def _hqi_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime | date):
        return to_datetime(value).strftime(HQI_TFORMAT)
    return str(value)


def hqi_where(where: Where) -> str | None:
    """Build a HQI ``WHERE`` string (used by the ``Query`` method).

    ``where`` is either a raw HQI string, or a mapping ``{field: condition}``
    where each condition is a value (equality), a ``(min, max)`` tuple (range,
    a bound may be ``None``) or a list of values (one of them).
    """
    if where is None:
        return None
    if isinstance(where, str):
        return where.strip() or None
    conditions = []
    for field, value in where.items():
        field = check_identifier(field)
        if isinstance(value, tuple):
            if len(value) != 2:
                raise ValueError(f"A range must be a (min, max) tuple, got {value!r}")
            text = f"{_hqi_value(value[0])}/{_hqi_value(value[1])}"
        elif isinstance(value, list | set | frozenset):
            text = ",".join(_hqi_value(v) for v in value)
        else:
            text = _hqi_value(value)
        conditions.append(f"{field},{text}")
    return ";".join(conditions) or None
