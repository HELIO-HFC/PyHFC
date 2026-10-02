# SPDX-License-Identifier: EUPL-1.2
"""Shared fixtures for the pyhfc tests."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from xml.sax.saxutils import escape, quoteattr

import pytest

from pyhfc.api.client import HQIClient

#: Field description: (name, datatype) or (name, datatype, null value)
FieldSpec = tuple[str, str] | tuple[str, str, str]


def make_table_xml(
    name: str, rows: Sequence[dict[str, Any]], fields: Sequence[FieldSpec] | None = None
) -> str:
    """Build a VOTable TABLE element (field names are lower-cased, like the HFC does)."""
    if fields is None:
        fields = [(key, "char") for key in (rows[0] if rows else {})]
    lines = [f"<TABLE name={quoteattr('hqi-' + name)}>"]
    for spec in fields:
        attrs = f'datatype="{spec[1]}" name={quoteattr(spec[0].lower())}'
        if spec[1] == "char":
            attrs = 'arraysize="*" ' + attrs
        if len(spec) == 3:
            lines.append(f'<FIELD {attrs}><VALUES null="{spec[2]}" /></FIELD>')
        else:
            lines.append(f"<FIELD {attrs} />")
    lines.append("<DATA><TABLEDATA>")
    for row in rows:
        cells = "".join(
            "<TD />" if row.get(spec[0]) is None else f"<TD>{escape(str(row[spec[0]]))}</TD>"
            for spec in fields
        )
        lines.append(f"<TR>{cells}</TR>")
    lines.append("</TABLEDATA></DATA></TABLE>")
    return "\n".join(lines)


def make_response(
    rows: Sequence[dict[str, Any]] = (),
    fields: Sequence[FieldSpec] | None = None,
    table: str = "VIEW_TEST",
    status: str = "OK",
    error: str | None = None,
    tables: Sequence[str] | None = None,
    envelope: bool = True,
) -> bytes:
    """Build a HQI response: a VOTable in a SOAP envelope.

    ``tables`` gives TABLE elements (from :func:`make_table_xml`), one RESOURCE each.
    """
    infos = [
        f'<INFO name="QUERY_STATUS" value="{status}" />',
        '<INFO name="EXECUTED_AT" value="2026-10-02 12:00:00" />',
    ]
    if error:
        infos.append(f'<INFO name="QUERY_ERROR" value={quoteattr(error)} />')
    infos.append(f'<INFO name="QUERY_STRING">SELECT * FROM {table}</INFO>')
    if tables is None:
        tables = [] if status == "ERROR" else [make_table_xml(table, rows, fields)]
    resources = tables or [""]
    body = "".join(
        f"<RESOURCE><DESCRIPTION>HFC Query Interface</DESCRIPTION>{''.join(infos)}{t}</RESOURCE>"
        for t in resources
    )
    votable = (
        f'<VOTABLE xmlns="http://www.ivoa.net/xml/VOTable/v1.1" version="1.1">{body}</VOTABLE>'
    )
    if not envelope:
        return votable.encode()
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        '<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/"><S:Body>'
        '<helio:queryResponse xmlns:helio="http://helio-vo.eu/xml/QueryService/v0.1">'
        f"{votable}</helio:queryResponse></S:Body></S:Envelope>"
    ).encode()


class FakeService:
    """Fake suds service: returns the queued responses, and records the calls."""

    METHODS = ("SQLSelect", "Query", "TimeQuery", "getTableNames", "getTableFields")

    def __init__(self) -> None:
        self.responses: list[bytes | Exception] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        for method in self.METHODS:
            setattr(self, method, self._method(method))

    def _method(self, name: str) -> Any:
        def call(**kwargs: Any) -> bytes:
            self.calls.append((name, kwargs))
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        return call

    @property
    def params(self) -> list[dict[str, Any]]:
        """Parameters of the calls."""
        return [params for _, params in self.calls]


@pytest.fixture(autouse=True)
def isolated_user_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never use the cache and the settings of the user in the tests."""
    monkeypatch.setenv("PYHFC_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PYHFC_CONFIG_DIR", str(tmp_path / "config"))


@pytest.fixture
def fake_service(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeService]:
    """Replace the SOAP client of every HQIClient by a fake service."""
    service = FakeService()
    fake_client = SimpleNamespace(service=service)
    monkeypatch.setattr(HQIClient, "soap_client", property(lambda self: fake_client))
    yield service


@pytest.fixture
def hqi(fake_service: FakeService) -> HQIClient:
    return HQIClient()
