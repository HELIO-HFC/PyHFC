# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

import contextlib
import io
import re
import tkinter as tk
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from tkinter import ttk

import numpy as np
import pytest
from conftest import FakeService, make_response
from PIL import Image

from pyhfc import __version__
from pyhfc.api import HQIClient, sql_where
from pyhfc.api.sql import nearest_date_order
from pyhfc.hfcviewer import cache as cache_module
from pyhfc.hfcviewer import theme, viewer

DATE = datetime(2012, 6, 1, 12, 0, 0)


def png_bytes(size: tuple[int, int] = (64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("L", size).save(buffer, format="PNG")
    return buffer.getvalue()


#: Content of a 64x64 quicklook image
PNG_64 = png_bytes()

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
        ("latest", "(DATE_OBS <= '2012-06-01 12:00:00')", "DATE_OBS DESC"),
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


def test_parse_args_defaults() -> None:
    args = viewer.parse_args([])
    assert args.date is None
    assert (args.observatory, args.instrument) == ("SDO", "AIA")
    assert args.features == ["ar", "ch"]


@pytest.mark.parametrize(
    ("text", "features"),
    [("ar,ch", ["ar", "ch"]), (" SP , fi ", ["sp", "fi"]), ("", []), ("ar,", ["ar"])],
)
def test_parse_features(text: str, features: list[str]) -> None:
    assert viewer.parse_features(text) == features
    assert viewer.parse_args(["-f", text]).features == features


def test_parse_features_unknown(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(ValueError, match="Unknown feature"):
        viewer.parse_features("ar,xx")
    with pytest.raises(SystemExit):
        viewer.parse_args(["-f", "xx"])
    assert "Unknown feature" in capsys.readouterr().err


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
    monkeypatch.setattr(viewer, "fetch_image", lambda url, timeout=30: PNG_64)
    fake_service.responses += [
        make_response([OBS_ROW]),  # initial nearest observation
        make_response([FEATURE_ROW]),  # active regions
        make_response([{**OBS_ROW, "DATE_OBS": "2012-06-03T08:00:00"}]),  # next
        make_response([], [("DATE_OBS", "char")]),  # no active regions at the next date
    ]

    app = viewer.Viewer(
        root,
        date="2012-06-01T12:00:00",
        observatory="Meudon",
        instrument="Spectroheliograph",
        features=[],
    )
    assert app.dataset.label == "MEUDON_SH_HA"
    assert app._date.get() == "2012-06-02T07:01:45"
    assert app.image is not None
    assert len(app._plt.images) == 1
    assert app._plt.get_title(loc="left") == "Meudon / Spectroheliograph Hα  ·  656.3 nm"
    assert app._date_text.get_text() == "2012-06-02 07:01:45 UTC"
    assert app._plt.get_xlabel() == "X  [arcsec]"
    assert app._plt.get_ylabel() == "Y  [arcsec]"

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


def test_viewer_gui_defaults(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """By default: the most recent SDO/AIA observation at the current date and time,
    with the active regions and the coronal holes."""
    monkeypatch.setattr(viewer, "fetch_image", lambda url, timeout=30: PNG_64)
    fake_service.responses += [
        make_response([OBS_ROW]),  # most recent SDO/AIA observation at the current time
        make_response([FEATURE_ROW]),  # active regions
        make_response([], [("DATE_OBS", "char")]),  # no coronal holes
    ]
    before = datetime.now().replace(microsecond=0)
    app = viewer.Viewer(root)
    after = datetime.now()

    assert app.dataset.label == "SDO_AIA"
    assert {key for key, var in app._feat_on.items() if var.get()} == {"ar", "ch"}

    observation, active_regions, coronal_holes = fake_service.params
    # most recent observation at the current date and time
    assert observation["FROM"] == [viewer.OBS_HFC_TABLE]
    assert "(UPPER(OBSERVAT) = 'SDO')" in observation["WHERE"]
    assert "(UPPER(INSTRUME) = 'AIA')" in observation["WHERE"]
    assert observation["ORDER_BY"] == "DATE_OBS DESC"
    assert observation["LIMIT"] == 1
    match = re.search(r"\(DATE_OBS <= '([^']+)'\)", observation["WHERE"])
    assert match is not None
    assert before <= datetime.fromisoformat(match.group(1)) <= after
    # both features are loaded and plotted
    assert active_regions["FROM"] == ["VIEW_AR_HQI"]
    assert coronal_holes["FROM"] == ["VIEW_CH_HQI"]
    assert len(app._plt.lines) == 1


def test_viewer_gui_latest_button(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The "Latest" button loads the most recent observation at the current date and time."""
    monkeypatch.setattr(viewer, "fetch_image", lambda url, timeout=30: PNG_64)
    fake_service.responses += [
        make_response([OBS_ROW]),  # observation nearest to the given date
        make_response([{**OBS_ROW, "DATE_OBS": "2026-10-02T07:59:33"}]),  # latest
    ]
    app = viewer.Viewer(root, date="2012-06-01T12:00:00", features=[])
    assert app._date.get() == "2012-06-02T07:01:45"
    assert app._latest_btn.cget("text") == "Latest"

    before = datetime.now().replace(microsecond=0)
    app._latest_btn.invoke()
    after = datetime.now()

    assert app._date.get() == "2026-10-02T07:59:33"
    latest = fake_service.params[1]
    assert latest["ORDER_BY"] == "DATE_OBS DESC"
    assert latest["LIMIT"] == 1
    assert "(UPPER(INSTRUME) = 'AIA')" in latest["WHERE"]
    match = re.search(r"\(DATE_OBS <= '([^']+)'\)", latest["WHERE"])
    assert match is not None
    assert before <= datetime.fromisoformat(match.group(1)) <= after


FEATURE_SETS = [[f.key for f in viewer.FEATURES], ["ar", "ch"], ["sp", "rs", "pr", "fi"], []]


@pytest.mark.parametrize("features", FEATURE_SETS, ids=lambda keys: ",".join(keys) or "none")
@pytest.mark.parametrize("dataset", viewer.DATASETS, ids=lambda ds: ds.label)
def test_viewer_gui_latest_any_dataset_and_features(
    root: tk.Tk,
    fake_service: FakeService,
    monkeypatch: pytest.MonkeyPatch,
    dataset: viewer.DataSet,
    features: list[str],
) -> None:
    """The "Latest" button works whatever the selected data set and features."""
    monkeypatch.setattr(viewer, "fetch_image", lambda url, timeout=30: PNG_64)
    fake_service.responses.append(make_response([OBS_ROW]))  # initial observation
    app = viewer.Viewer(root, date="2012-06-01T12:00:00", features=[])

    # select the data set and the features
    app._obsid.set(viewer.DATASETS.index(dataset))
    for key, var in app._feat_on.items():
        var.set(int(key in features))
    checked = [feature for feature in viewer.FEATURES if feature.key in features]
    fake_service.responses.append(make_response([{**OBS_ROW, "DATE_OBS": "2026-10-02T07:59:33"}]))
    fake_service.responses += [make_response([FEATURE_ROW]) for _ in checked]

    app._latest_btn.invoke()

    assert app._date.get() == "2026-10-02T07:59:33"
    latest, *feature_queries = fake_service.params[1:]
    # the most recent observation of the selected data set
    assert latest["FROM"] == [dataset.table]
    assert latest["WHERE"].startswith(f"({dataset.where()}) AND ((DATE_OBS <= '")
    assert latest["ORDER_BY"] == "DATE_OBS DESC"
    # all the checked features, around the date of this observation
    assert [q["FROM"] for q in feature_queries] == [[f.table] for f in checked]
    for query in feature_queries:
        assert "'2026-10-02 06:59:33' AND '2026-10-02 08:59:33'" in query["WHERE"]
    assert len(app._plt.lines) == len(checked)
    assert app.image is not None


@pytest.mark.parametrize(
    ("wavemin", "waveunit", "text"),
    [
        ("17.1", "NM", "17.1 nm"),
        (656.3, "nm", "656.3 nm"),
        ("617.133", "NM", "617.1 nm"),
        ("1.99862", "M", "150 MHz"),
        ("1.828", "M", "164 MHz"),
        ("5000", "A", "5000 Å"),
        ("12", "XX", "12 XX"),
        ("", "NM", "nm"),
    ],
)
def test_wavelength_text(wavemin: object, waveunit: str, text: str) -> None:
    assert viewer.wavelength_text(wavemin, waveunit) == text


def test_display_date() -> None:
    assert viewer.display_date("2012-06-02T07:01:45") == "2012-06-02 07:01:45 UTC"
    assert viewer.display_date(datetime(2012, 6, 2, 7, 1, 45)) == "2012-06-02 07:01:45 UTC"
    assert viewer.display_date("unknown") == "unknown"


def test_datasets_display_names() -> None:
    names = [dataset.display for dataset in viewer.DATASETS]
    assert len(set(names)) == len(names)
    assert all(" / " in name for name in names)


def test_viewer_gui_features_redraw(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Toggling a feature only redraws the contours: the image is processed once."""
    monkeypatch.setattr(viewer, "fetch_image", lambda url, timeout=30: PNG_64)
    conversions: list[object] = []
    image_to_array = viewer.image_to_array

    def counting_image_to_array(image: Image.Image) -> object:
        conversions.append(image)
        return image_to_array(image)

    monkeypatch.setattr(viewer, "image_to_array", counting_image_to_array)
    fake_service.responses += [
        make_response([OBS_ROW]),  # observation
        make_response([FEATURE_ROW, {**FEATURE_ROW, "TRACK_ID": 4}]),  # active regions
        make_response([], [("DATE_OBS", "char")]),  # no coronal holes
    ]
    app = viewer.Viewer(root, date="2012-06-01T12:00:00", features=["ar", "ch"])
    image = app._plt.images[0]
    assert len(app._plt.lines) == 2
    assert app._feat_count["ar"].get() == "2"
    assert app._feat_count["ch"].get() == "none"
    assert app._feat_count["sp"].get() == ""
    status = app._status.get()
    for text in ("SDO / AIA", "656.3 nm", "2012-06-02 07:01:45 UTC"):
        assert text in status
    assert "2 active regions" in status
    assert "no coronal holes" in status

    # unchecking a feature removes its contours, without reprocessing the image
    app._feat_on["ar"].set(0)
    app._draw_features()
    assert len(app._plt.lines) == 0
    assert app._feat_count["ar"].get() == ""
    assert "active regions" not in app._status.get()
    # checking it again uses the cached data (no new query)
    app._feat_on["ar"].set(1)
    app._draw_features()
    assert len(app._plt.lines) == 2
    assert len(fake_service.calls) == 3
    # the image artist is kept, and the image was processed only once
    assert list(app._plt.images) == [image]
    assert len(conversions) == 1


def test_viewer_gui_header(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The header shows the logo of the LIRA, and no date format hint."""
    monkeypatch.setattr(viewer, "fetch_image", lambda url, timeout=30: PNG_64)
    fake_service.responses.append(make_response([OBS_ROW]))
    app = viewer.Viewer(root, date="2012-06-01T12:00:00", features=[])
    assert app._logo is not None
    assert app._logo.height() == viewer.LOGO_HEIGHT

    def texts(widget: tk.Misc) -> list[str]:
        found = []
        for child in widget.winfo_children():
            with contextlib.suppress(tk.TclError):
                found.append(str(child.cget("text")))
            found += texts(child)
        return found

    all_texts = texts(app)
    assert not any(text.startswith("Format") for text in all_texts)
    assert "HFC" not in all_texts  # replaced by the logo


@pytest.mark.parametrize(
    ("key", "number", "text"),
    [
        ("rs", 1, "1 NRH source"),
        ("rs", 3, "3 NRH sources"),
        ("ar", 4, "4 active regions"),
        ("ch", 0, "no coronal holes"),
        ("sp", 1, "1 sunspot"),
    ],
)
def test_feature_count_text(key: str, number: int, text: str) -> None:
    assert viewer.FEATURE_BY_KEY[key].count_text(number) == text


# ________________ Image cache ___________________


@pytest.fixture
def cached_viewer(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[str], list[tuple[str, str]], Callable[..., viewer.Viewer]]:
    """Factory of viewers, recording the downloads and the message boxes."""
    downloads: list[str] = []
    boxes: list[tuple[str, str]] = []

    def fetch(url: str, timeout: float = 30) -> bytes:
        downloads.append(url)
        return PNG_64

    monkeypatch.setattr(viewer, "fetch_image", fetch)
    for kind in ("showwarning", "showinfo", "showerror"):
        monkeypatch.setattr(
            f"tkinter.messagebox.{kind}",
            lambda title, msg, kind=kind, **kw: boxes.append((kind, msg)),
        )

    def make(**kwargs: object) -> viewer.Viewer:
        fake_service.responses.append(make_response([OBS_ROW]))
        return viewer.Viewer(root, date="2012-06-01T12:00:00", features=[], **kwargs)  # type: ignore[arg-type]

    return downloads, boxes, make


def test_viewer_cache_reuses_images(
    cached_viewer: tuple[list[str], list[tuple[str, str]], Callable[..., viewer.Viewer]],
) -> None:
    downloads, boxes, make = cached_viewer
    first = make()
    assert downloads == ["ftp://example.org/qclk/image.png"]
    assert first._cache.count(cache_module.IMAGES) == 1
    assert first._cache.count(cache_module.HQI) == 1  # the observation query
    assert first._cache.directory == cache_module.user_cache_dir()
    # the image of the same observation is read from the disk cache
    second = make()
    assert len(downloads) == 1
    assert second.image is not None
    assert second.image.size == (64, 64)
    assert boxes == []


def test_viewer_cache_invalid_file(
    cached_viewer: tuple[list[str], list[tuple[str, str]], Callable[..., viewer.Viewer]],
) -> None:
    downloads, _, make = cached_viewer
    app = make()
    app._cache.path(downloads[0]).write_bytes(b"corrupted")
    app = make()
    # downloaded again, and the cache fixed
    assert len(downloads) == 2
    assert app.image is not None
    assert app._cache.get(downloads[0]) == PNG_64


def test_viewer_cache_full(
    cached_viewer: tuple[list[str], list[tuple[str, str]], Callable[..., viewer.Viewer]],
    tmp_path: Path,
) -> None:
    downloads, boxes, make = cached_viewer
    small = cache_module.DiskCache(tmp_path / "small", 0)
    app = make(cache=small)
    # the data are displayed, but not cached, and the user is warned once
    assert app.image is not None
    assert len(small) == 0
    assert small.full
    assert [kind for kind, _ in boxes] == ["showwarning"]
    assert "The cache is full" in boxes[0][1]
    assert "Settings menu" in boxes[0][1]
    app._load_qclk()
    assert len(boxes) == 1  # no new warning
    assert len(small) == 0  # nothing new cached

    # increasing the maximum size (saved in the settings) resumes the caching
    app._set_cache_max_size(1)
    assert cache_module.Settings.load().cache_max_size_mb == 1
    assert small.max_size == cache_module.MB
    assert not small.full
    app._load_qclk()
    assert small.count(cache_module.IMAGES) == 1
    assert len(downloads) == 3


def test_viewer_empty_cache(
    cached_viewer: tuple[list[str], list[tuple[str, str]], Callable[..., viewer.Viewer]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, boxes, make = cached_viewer
    app = make()
    assert len(app._cache) == 2  # the image and the observation query
    answers = [False, True]
    monkeypatch.setattr("tkinter.messagebox.askyesno", lambda title, msg: answers.pop(0))
    app._empty_cache()  # cancelled
    assert len(app._cache) == 2
    app._empty_cache()
    assert len(app._cache) == 0
    assert app._status.get() == "2 cached files removed"
    app._empty_cache()
    assert boxes[-1] == ("showinfo", "The cache is already empty.")


def test_viewer_settings_menu_and_dialog(
    cached_viewer: tuple[list[str], list[tuple[str, str]], Callable[..., viewer.Viewer]],
) -> None:
    _, boxes, make = cached_viewer
    app = make()
    last = app._menubar.index("end")
    assert last is not None
    menus = [app._menubar.entrycget(i, "label") for i in range(last + 1)]
    assert "Settings" in menus

    app._cache_dialog()
    dialog = app._dialog
    assert dialog is not None
    assert dialog.title() == "Cache"

    def widgets(widget: tk.Misc) -> list[tk.Misc]:
        children = widget.winfo_children()
        return children + [w for child in children for w in widgets(child)]

    found = widgets(dialog)
    spinbox = next(w for w in found if isinstance(w, ttk.Spinbox))
    buttons = {w.cget("text"): w for w in found if isinstance(w, ttk.Button)}
    labels = [str(w.cget("text")) for w in found if isinstance(w, ttk.Label)]
    assert spinbox.get() == "500"
    assert {"Empty the cache", "Cancel", "Save"} <= set(buttons)
    usages = [
        w.getvar(str(w.cget("textvariable")))
        for w in found
        if isinstance(w, ttk.Label) and str(w.cget("textvariable"))
    ]
    assert usages == [app._cache_usage()]
    assert usages[0].endswith("MB used of 500 MB (1 image, 1 HQI response)")
    assert "Maximum size" in labels

    spinbox.set("abc")
    buttons["Save"].invoke()
    assert boxes[-1][0] == "showerror"
    assert dialog.winfo_exists()

    spinbox.set("250")
    buttons["Save"].invoke()
    assert not dialog.winfo_exists()
    assert app._cache.max_size == 250 * cache_module.MB
    assert cache_module.Settings.load().cache_max_size_mb == 250


@pytest.mark.parametrize(("number", "text"), [(0, "0 images"), (1, "1 image"), (3, "3 images")])
def test_plural(number: int, text: str) -> None:
    assert viewer.plural(number, "image") == text


def test_viewer_cache_hqi_responses(
    cached_viewer: tuple[list[str], list[tuple[str, str]], Callable[..., viewer.Viewer]],
    fake_service: FakeService,
    root: tk.Tk,
) -> None:
    """The observation and the features of a date are read from the cache the next times."""
    downloads, _, _ = cached_viewer
    fake_service.responses += [make_response([OBS_ROW]), make_response([FEATURE_ROW])]
    first = viewer.Viewer(root, date="2012-06-01T12:00:00", features=["ar"])
    assert len(fake_service.calls) == 2
    assert first._cache.count(cache_module.HQI) == 2
    lines = [np.asarray(line.get_xydata()).tolist() for line in first._plt.lines]

    # no query to the service, nor download: everything comes from the cache
    second = viewer.Viewer(root, date="2012-06-01T12:00:00", features=["ar"])
    assert len(fake_service.calls) == 2
    assert len(downloads) == 1
    assert second._date.get() == first._date.get()
    assert [np.asarray(line.get_xydata()).tolist() for line in second._plt.lines] == lines
    assert second._status.get() == first._status.get()


def test_viewer_latest_not_cached(
    cached_viewer: tuple[list[str], list[tuple[str, str]], Callable[..., viewer.Viewer]],
    fake_service: FakeService,
    root: tk.Tk,
) -> None:
    """The most recent observation is always queried (it depends on the current date)."""
    fake_service.responses += [make_response([OBS_ROW]), make_response([OBS_ROW])]
    app = viewer.Viewer(root, features=[])
    app._latest_btn.invoke()
    assert len(fake_service.calls) == 2
    assert app._cache.count(cache_module.HQI) == 0


# ________________ Server checks and links _______


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Urls opened in the browser."""
    urls: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: urls.append(url))
    return urls


def diode_color(app: viewer.Viewer, key: str) -> str:
    canvas, item, _ = app._diodes[key]
    return str(canvas.tk.call(str(canvas), "itemcget", item, "-fill"))


def test_viewer_server_checks(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(viewer, "fetch_image", lambda url, timeout=30: PNG_64)
    checked: list[str] = []

    def check(hqi: HQIClient, image_url: str) -> tuple[bool, bool]:
        checked.append(image_url)
        return True, False

    monkeypatch.setattr(viewer, "check_servers", check)
    fake_service.responses.append(make_response([OBS_ROW]))
    app = viewer.Viewer(root, date="2012-06-01T12:00:00", features=[])
    # not checked yet: grey lights, a check is scheduled immediately
    assert diode_color(app, "hqi") == diode_color(app, "ftp") == theme.UNKNOWN
    assert "not checked yet" in app._diodes["hqi"][2].text
    assert app._ping_job is not None

    # the check runs in a thread, its result is then shown
    app._start_ping()
    assert app._ping_thread is not None
    app._ping_thread.join(timeout=5)
    app._poll_ping()
    assert checked == ["ftp://example.org/qclk"]  # server of the displayed image
    assert diode_color(app, "hqi") == theme.OK
    assert diode_color(app, "ftp") == theme.KO
    assert app._diodes["hqi"][2].text.startswith(
        "HQI service (observations and features): reachable"
    )
    assert "Images server: NOT reachable (checked at" in app._diodes["ftp"][2].text
    # the next check is scheduled after the interval
    assert app._ping_job is not None


def test_viewer_server_check_interval(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(viewer, "fetch_image", lambda url, timeout=30: PNG_64)
    delays: list[int | None] = []
    fake_service.responses.append(make_response([OBS_ROW]))
    app = viewer.Viewer(root, date="2012-06-01T12:00:00", features=[])
    assert app._settings.ping_interval_s == 60
    schedule = app._schedule_ping

    def recording_schedule(delay_ms: int | None = None) -> None:
        delays.append(delay_ms)
        schedule(delay_ms)

    monkeypatch.setattr(app, "_schedule_ping", recording_schedule)
    app._set_ping_interval(120)
    assert cache_module.Settings.load().ping_interval_s == 120
    assert delays == [None]  # rescheduled with the new interval
    app._set_ping_interval(1)
    assert app._settings.ping_interval_s == cache_module.MIN_PING_INTERVAL_S


def test_viewer_server_checks_dialog(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(viewer, "fetch_image", lambda url, timeout=30: PNG_64)
    errors: list[str] = []
    monkeypatch.setattr("tkinter.messagebox.showerror", lambda title, msg, **kw: errors.append(msg))
    fake_service.responses.append(make_response([OBS_ROW]))
    app = viewer.Viewer(root, date="2012-06-01T12:00:00", features=[])
    last = app._menubar.index("end")
    assert last is not None
    settings_menu = next(
        app._menubar.nametowidget(app._menubar.entrycget(i, "menu"))
        for i in range(last + 1)
        if app._menubar.entrycget(i, "label") == "Settings"
    )
    entries = [
        settings_menu.entrycget(i, "label")
        for i in range((settings_menu.index("end") or 0) + 1)
        if settings_menu.type(i) == "command"
    ]
    assert entries == ["Cache…", "Empty the cache…", "Server checks…"]

    app._ping_dialog()
    dialog = app._dialog
    assert dialog is not None
    assert dialog.title() == "Server checks"
    found = all_widgets(dialog)
    spinbox = next(w for w in found if isinstance(w, ttk.Spinbox))
    buttons = {w.cget("text"): w for w in found if isinstance(w, ttk.Button)}
    assert spinbox.get() == "60"
    assert {"Check now", "Cancel", "Save"} <= set(buttons)
    buttons["Check now"].invoke()  # immediate check
    assert app._ping_job is not None
    spinbox.set("5")
    buttons["Save"].invoke()
    assert errors and "at least 10" in errors[0]
    spinbox.set("300")
    buttons["Save"].invoke()
    assert not dialog.winfo_exists()
    assert cache_module.Settings.load().ping_interval_s == 300


def all_widgets(widget: tk.Misc) -> list[tk.Misc]:
    children = widget.winfo_children()
    return children + [w for child in children for w in all_widgets(child)]


def test_pypi_url() -> None:
    assert viewer.pypi_url("0.3.0") == "https://pypi.org/project/pyhfc/0.3.0/"
    assert viewer.pypi_url("1.2.0rc1") == "https://pypi.org/project/pyhfc/1.2.0rc1/"
    assert viewer.pypi_url("unknown") == "https://pypi.org/project/pyhfc/"


def test_viewer_links(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch, opened: list[str]
) -> None:
    monkeypatch.setattr(viewer, "fetch_image", lambda url, timeout=30: PNG_64)
    fake_service.responses.append(make_response([OBS_ROW]))
    app = viewer.Viewer(root, date="2012-06-01T12:00:00", features=[])
    # version of pyhfc, in the status bar: link to its PyPI page
    assert app._version_link.cget("text") == f"pyhfc {__version__}"
    assert app._version_link.url == viewer.pypi_url()
    app._version_link.event_generate("<Button-1>")
    # logo of the LIRA: link to its home page
    app._logo_label.event_generate("<Button-1>")
    assert opened == [viewer.pypi_url(), "https://lira.obspm.fr/"]


def test_viewer_about(
    root: tk.Tk, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch, opened: list[str]
) -> None:
    monkeypatch.setattr(viewer, "fetch_image", lambda url, timeout=30: PNG_64)
    fake_service.responses.append(make_response([OBS_ROW]))
    app = viewer.Viewer(root, date="2012-06-01T12:00:00", features=[])
    app._about()
    dialog = app._dialog
    assert dialog is not None
    assert dialog.title() == "About HFC Viewer"
    labels = [w for w in all_widgets(dialog) if isinstance(w, ttk.Label)]
    links = {str(w.cget("text")): w.url for w in labels if isinstance(w, viewer.Link)}
    assert links == {
        f"pyhfc {__version__}": viewer.pypi_url(),
        "LIRA-Observatoire de Paris": "https://lira.obspm.fr/",
        "http://voparis-helio.obspm.fr/hfc-gui/": "http://voparis-helio.obspm.fr/hfc-gui/",
        "http://www.helio-vo.eu/": "http://www.helio-vo.eu/",
        "helio.support@sympa.obspm.fr": "mailto:helio.support@sympa.obspm.fr",
    }
    texts = " ".join(str(w.cget("text")) for w in labels)
    assert "xavier" not in texts.lower()
    next(w for w in labels if w.cget("text") == "helio.support@sympa.obspm.fr").event_generate(
        "<Button-1>"
    )
    assert opened == ["mailto:helio.support@sympa.obspm.fr"]
