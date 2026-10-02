# SPDX-License-Identifier: EUPL-1.2
"""Tests querying the live HFC web service (run with ``pytest -m network``)."""

from __future__ import annotations

from datetime import datetime

import pytest

from pyhfc.api import HQIClient, HQIQueryError, load_image
from pyhfc.hfcviewer import viewer

pytestmark = pytest.mark.network

DATE = datetime(2012, 6, 1, 12, 0, 0)


@pytest.fixture(scope="module")
def hqi() -> HQIClient:
    return HQIClient()


def test_tables_and_fields(hqi: HQIClient) -> None:
    tables = hqi.tables()
    assert {"VIEW_AR_HQI", "VIEW_OBS_HQI", "VIEW_PP_HQI"} <= set(tables)
    assert {"DATE_OBS", "CC", "FEAT_AREA_DEG2"} <= set(hqi.fields("VIEW_AR_HQI"))


def test_select_typed(hqi: HQIClient) -> None:
    response = hqi.select(
        "VIEW_AR_HQI",
        what="DATE_OBS, JDINT, R_SUN, NOAA_NUMBER",
        where={"DATE_OBS": (DATE, "2012-06-01T13:00:00"), "OBSERVAT": "SDO"},
        order_by="DATE_OBS",
        limit=5,
    )
    assert 0 < len(response) <= 5
    row = response.first()
    assert row is not None
    assert isinstance(row["DATE_OBS"], datetime)
    assert isinstance(row["JDINT"], int)
    assert isinstance(row["R_SUN"], float)
    assert response.votable.startswith(b"<?xml")


def test_select_error(hqi: HQIClient) -> None:
    with pytest.raises(HQIQueryError):
        hqi.select("NO_SUCH_TABLE")


def test_time_query_and_query(hqi: HQIClient) -> None:
    response = hqi.time_query("VIEW_AR_HQI", DATE, "2012-06-01T14:00:00", max_records=3)
    assert 0 < len(response) <= 3
    response = hqi.query(
        "VIEW_AR_HQI",
        "2012-06-01T00:00:00",
        "2012-06-01T12:00:00",
        where={"OBSERVAT": "SDO", "FEAT_AREA_DEG2": (10, None)},
    )
    assert response.rows
    assert {row["OBSERVAT"] for row in response} == {"SDO"}
    assert min(row["FEAT_AREA_DEG2"] for row in response) >= 10


def test_features_and_quicklook(hqi: HQIClient) -> None:
    response = hqi.features("sunspots", "2012-06-01T11:00:00", "2012-06-01T13:00:00", limit=2)
    assert len(response) == 2
    image = hqi.quicklook(response[0])
    assert image is not None


def test_to_astropy(hqi: HQIClient) -> None:
    pytest.importorskip("astropy")
    response = hqi.select("VIEW_AR_HQI", what="DATE_OBS, R_SUN", limit=3)
    table = response.to_astropy()
    assert len(table) == 3


@pytest.mark.parametrize("label", ["MEUDON_SH_HA", "SDO_HMI_I", "SOHO_EIT"])
def test_viewer_observation(label: str) -> None:
    dataset = next(ds for ds in viewer.DATASETS if ds.label == label)
    row = viewer.load_observation(HQIClient(typed=False), dataset, DATE)
    assert row is not None
    assert set(viewer.OBS_FIELDS.replace(" ", "").split(",")) <= set(row)
    assert load_image(f"{row['QCLK_URL']}/{row['QCLK_FNAME']}") is not None


def test_viewer_features() -> None:
    feature = viewer.FEATURE_BY_KEY["ar"]
    response = HQIClient(typed=False).select(**viewer.feature_query(feature, DATE))
    rows = viewer.closest_rows(response.rows, DATE)
    assert rows
    assert any(viewer.feature_contour(row) is not None for row in rows)
