# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from datetime import datetime

import numpy as np
import pytest
from conftest import FakeService, make_response
from PIL import Image

from pyhfc.api import HQIClient, sql_where
from pyhfc.api.sql import nearest_date_order
from pyhfc.hfcviewer import viewer

DATE = datetime(2012, 6, 1, 12, 0, 0)

OBS_ROW = {
    "DATE_OBS": "2012-06-02T07:01:45",
    "CDELT1": 2.0,
    "CDELT2": 2.0,
    "NAXIS1": 64,
    "NAXIS2": 64,
    "CENTER_X": 31.5,
    "CENTER_Y": 31.5,
    "R_SUN": 25.0,
    "QCLK_URL": "ftp://example.org/qclk",
    "QCLK_FNAME": "image.png",
    "WAVEMIN": 656.3,
    "WAVEUNIT": "NM",
}

FEATURE_ROW = {
    "DATE_OBS": "2012-06-02T07:01:45",
    "CDELT1": 2.0,
    "CDELT2": 2.0,
    "NAXIS1": 64,
    "NAXIS2": 64,
    "CENTER_X": 31.5,
    "CENTER_Y": 31.5,
    "CC": "0246",
    "CC_X_PIX": 10,
    "CC_Y_PIX": 20,
    "TRACK_ID": 3,
}


@pytest.mark.parametrize(
    ("args", "label"),
    [
        (("Nancay", "Radioheliograph"), "NANCAY_RH"),
        (("SDO", "HMI"), "SDO_HMI_I"),
        (("sdo", "hmi", "magnetogram"), "SDO_HMI_M"),
        (("SOHO", "MDI", "continuum"), "SOHO_MDI_I"),
        (("Meudon", "Spectroheliograph", "", "Halpha"), "MEUDON_SH_HA"),
        (("Meudon", "Spectroheliograph", "", "CaII K3"), "MEUDON_SH_K3"),
        (("Meudon", "Spectroheliograph", "", "unknown"), "MEUDON_SH_HA"),
    ],
)
def test_find_dataset(args: tuple[str, ...], label: str) -> None:
    index = viewer.find_dataset(*args)
    assert index is not None
    assert viewer.DATASETS[index].label == label


def test_find_dataset_unknown() -> None:
    assert viewer.find_dataset("Unknown", "Instrument") is None


def test_dataset_where_and_title() -> None:
    dataset = viewer.DATASETS[viewer.find_dataset("Meudon", "Spectroheliograph") or 0]
    assert dataset.where() == (
        "(UPPER(OBSERVAT) = 'MEUDON') AND (UPPER(INSTRUME) = 'SPECTROHELIOGRAPH')"
        " AND (UPPER(WAVENAME) = 'HALPHA')"
    )
    assert dataset.title == "Meudon-Spectroheliograph-Halpha"
    assert dataset.table == viewer.PP_HFC_TABLE


@pytest.mark.parametrize(
    ("direction", "where", "order"),
    [
        ("nearest", None, nearest_date_order(DATE)),
        ("previous", "(DATE_OBS < '2012-06-01 12:00:00')", "DATE_OBS DESC"),
        ("next", "(DATE_OBS > '2012-06-01 12:00:00')", "DATE_OBS ASC"),
    ],
)
def test_load_observation(
    fake_service: FakeService, direction: str, where: str | None, order: str
) -> None:
    fake_service.responses.append(make_response([OBS_ROW]))
    dataset = viewer.DATASETS[0]
    row = viewer.load_observation(HQIClient(typed=False), dataset, DATE, direction)
    # the values are kept as strings
    assert row == {key: str(value) for key, value in OBS_ROW.items()}
    (params,) = fake_service.params
    assert params["WHAT"] == viewer.OBS_FIELDS
    assert params["FROM"] == [viewer.OBS_HFC_TABLE]
    expected_where = dataset.where() if where is None else f"({dataset.where()}) AND ({where})"
    assert params["WHERE"] == expected_where
    assert params["ORDER_BY"] == order
    assert params["LIMIT"] == 1


def test_load_observation_not_found(fake_service: FakeService) -> None:
    fake_service.responses.append(make_response([], [("DATE_OBS", "char")]))
    assert viewer.load_observation(HQIClient(), viewer.DATASETS[0], DATE, "next") is None


def test_load_observation_bad_direction() -> None:
    with pytest.raises(ValueError):
        viewer.load_observation(HQIClient(), viewer.DATASETS[0], DATE, "sideways")


def test_feature_query() -> None:
    params = viewer.feature_query(viewer.FEATURE_BY_KEY["ar"], DATE)
    assert params["table"] == "VIEW_AR_HQI"
    assert params["what"] == viewer.FEATURE_FIELDS
    assert sql_where(params["where"]) == (
        "(DATE_OBS BETWEEN '2012-06-01 11:00:00' AND '2012-06-01 13:00:00')"
    )


def test_closest_rows() -> None:
    rows = [
        {"DATE_OBS": "2012-06-01T11:00:00", "ID": 1},
        {"DATE_OBS": "2012-06-01T12:30:00", "ID": 2},
        {"DATE_OBS": "2012-06-01T12:30:00", "ID": 3},
    ]
    assert [row["ID"] for row in viewer.closest_rows(rows, DATE)] == [2, 3]
    assert viewer.closest_rows([], DATE) == []
    # typed rows
    rows = [{**row, "DATE_OBS": datetime.fromisoformat(str(row["DATE_OBS"]))} for row in rows]
    assert [row["ID"] for row in viewer.closest_rows(rows, DATE)] == [2, 3]


@pytest.mark.parametrize("track_id", [1, 2, 1000, 123456])
def test_track_color(track_id: int) -> None:
    color = viewer.track_color(track_id)
    assert all(0.0 <= c < 1.0 for c in color)


def test_track_color_distinct() -> None:
    assert viewer.track_color(1) != viewer.track_color(2)


def test_feature_contour() -> None:
    contour = viewer.feature_contour(FEATURE_ROW)
    assert contour is not None
    xs, ys = contour
    np.testing.assert_allclose(xs, 2.0 * (np.array([10, 9, 9, 10, 10]) - 31.5))
    np.testing.assert_allclose(ys, 2.0 * (np.array([20, 20, 19, 19, 20]) - 31.5))


def test_feature_contour_invalid() -> None:
    # prominences have non-integer chain code starting pixels
    assert viewer.feature_contour({**FEATURE_ROW, "CC_X_PIX": "B12"}) is None
    assert viewer.feature_contour({"CC": "01"}) is None


@pytest.mark.parametrize("mode", ["L", "P", "I;16", "1"])
def test_image_to_array_grayscale(mode: str) -> None:
    image = Image.new(mode, (8, 4))
    data = viewer.image_to_array(image)
    assert data.shape == (4, 8)
    assert data.dtype == np.float64


def test_image_to_array_rgb_is_flipped() -> None:
    image = Image.new("RGB", (2, 2))
    image.putpixel((0, 0), (255, 0, 0))
    data = viewer.image_to_array(image)
    assert data.shape == (2, 2, 3)
    assert tuple(data[1, 0]) == (255, 0, 0)


def test_parse_args() -> None:
    args = viewer.parse_args(["-d", "2012-06-01T12:00:00", "-o", "Meudon", "-x", "800"])
    assert args.date == "2012-06-01T12:00:00"
    assert args.observatory == "Meudon"
    assert args.instrument == viewer.INSTRUMENT
    assert args.xsize == 800
    assert args.ysize is None


# ________________ GUI ___________________________


@pytest.fixture
def root() -> Iterator[tk.Tk]:
    try:
        root = tk.Tk()
    except tk.TclError as err:  # pragma: no cover - no display available
        pytest.skip(f"Tk is not available: {err}")
    root.withdraw()
    yield root
    root.destroy()


def test_viewer_gui(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(viewer, "load_image", lambda url, timeout=30: Image.new("L", (64, 64)))
    fake_service.responses += [
        make_response([OBS_ROW]),  # initial nearest observation
        make_response([FEATURE_ROW]),  # active regions
        make_response([{**OBS_ROW, "DATE_OBS": "2012-06-03T08:00:00"}]),  # next
        make_response([], [("DATE_OBS", "char")]),  # no active regions at the next date
    ]

    app = viewer.Viewer(
        root, date="2012-06-01T12:00:00", observatory="Meudon", instrument="Spectroheliograph"
    )
    assert app.dataset.label == "MEUDON_SH_HA"
    assert app._date.get() == "2012-06-02T07:01:45"
    assert app.image is not None
    assert len(app._plt.images) == 1
    assert app._plt.get_title() == "Meudon-Spectroheliograph-Halpha [656.3 NM]"

    # Overplot active regions: they are queried once, then cached
    app._feat_on["ar"].set(1)
    app._plot_qclk()
    app._plot_qclk()
    assert len(app._plt.lines) == 1
    assert len(fake_service.calls) == 2
    assert fake_service.params[1]["FROM"] == ["VIEW_AR_HQI"]

    # Colors by tracking
    app._feat_ct.set(1)
    app._plot_qclk()
    assert app._plt.lines[0].get_color() == viewer.track_color(3)

    app._next_date()
    assert app._date.get() == "2012-06-03T08:00:00"
    assert "DATE_OBS > '2012-06-02 07:01:45'" in fake_service.params[2]["WHERE"]
    # features are reloaded for the new date
    assert fake_service.params[3]["FROM"] == ["VIEW_AR_HQI"]
    assert "2012-06-03 07:00:00" in fake_service.params[3]["WHERE"]
    assert not app._plt.lines


def test_viewer_gui_query_error(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors: list[str] = []
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda title, msg: errors.append(msg))
    fake_service.responses.append(make_response(status="ERROR", error="Bad SQL"))
    app = viewer.Viewer(root, date="2012-06-01T12:00:00")
    assert errors == ["QUERYING HFC HAS FAILED!"]
    assert app.obs_data is None
