# SPDX-License-Identifier: EUPL-1.2
"""Python viewer for the Heliophysics Feature Catalogue (HFC).

@author: Xavier Bonnin (LESIA)
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import re
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from tkinter import messagebox, ttk
from typing import Any

import numpy as np
from matplotlib import patheffects
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from numpy.typing import NDArray
from PIL import Image

from pyhfc import __version__
from pyhfc.api import HQI_DEV_WSDL, HQI_WSDL, HQIClient, HQIError, Row, load_image
from pyhfc.api.sql import and_conditions, sql_equals, sql_where, to_datetime
from pyhfc.api.tables import OBS_TABLE, PP_TABLE
from pyhfc.hfcviewer import theme
from pyhfc.improlib import auto_contrast, chain2image

__author__ = "Xavier Bonnin"
__email__ = "xavier.bonnin@obspm.fr"
__project__ = "HELIO (FP7 project No. 238969)"
__institute__ = "LESIA"

logger = logging.getLogger(__name__)

HQI_TFORMAT = "%Y-%m-%dT%H:%M:%S"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

# Helio Interface for HFC
URL_WSDL = HQI_WSDL
URL_WSDL_DEV = HQI_DEV_WSDL
OBS_HFC_TABLE = OBS_TABLE
PP_HFC_TABLE = PP_TABLE

OBS_FIELDS = (
    "DATE_OBS, CDELT1, CDELT2, NAXIS1, NAXIS2, CENTER_X, CENTER_Y, R_SUN, "
    "QCLK_URL, QCLK_FNAME, WAVEMIN, WAVEUNIT"
)
FEATURE_FIELDS = (
    "DATE_OBS, CDELT1, CDELT2, NAXIS1, NAXIS2, CENTER_X, CENTER_Y, CC, CC_X_PIX, CC_Y_PIX, TRACK_ID"
)

# Time window (around the observation date) used to look for features
FEATURE_TIME_WINDOW = timedelta(hours=1)


@dataclass(frozen=True)
class Feature:
    """A feature type stored in the HFC."""

    key: str
    label: str
    table: str
    color: str


FEATURES = (
    Feature("ar", "Active regions", "VIEW_AR_HQI", theme.FEATURE_COLORS["ar"]),
    Feature("ch", "Coronal holes", "VIEW_CH_HQI", theme.FEATURE_COLORS["ch"]),
    Feature("sp", "Sunspots", "VIEW_SP_HQI", theme.FEATURE_COLORS["sp"]),
    Feature("rs", "NRH sources", "VIEW_RS_HQI", theme.FEATURE_COLORS["rs"]),
    Feature("pr", "Prominences", "VIEW_PRO_HQI", theme.FEATURE_COLORS["pr"]),
    Feature("fi", "Filaments", "VIEW_FIL_HQI", theme.FEATURE_COLORS["fi"]),
)
FEATURE_BY_KEY = {feature.key: feature for feature in FEATURES}


@dataclass(frozen=True)
class DataSet:
    """A data set (observatory/instrument) displayable by the viewer."""

    label: str
    observatory: str
    instrument: str
    telescope: str = ""
    wavename: str = ""
    table: str = OBS_HFC_TABLE
    #: name displayed in the viewer
    name: str = ""

    @property
    def title(self) -> str:
        parts = (self.observatory, self.instrument, self.telescope, self.wavename)
        return "-".join(part for part in parts if part)

    @property
    def display(self) -> str:
        return self.name or self.title

    def where(self) -> str:
        """SQL condition selecting the observations of this data set."""
        conditions = [
            sql_equals("OBSERVAT", self.observatory),
            sql_equals("INSTRUME", self.instrument),
        ]
        if self.telescope:
            conditions.append(sql_equals("TELESCOP", self.telescope))
        if self.wavename:
            conditions.append(sql_equals("WAVENAME", self.wavename))
        return " AND ".join(conditions)


# List for observatory radio buttons
DATASETS = (
    DataSet("SDO_HMI_I", "SDO", "HMI", telescope="Continuum", name="SDO / HMI continuum"),
    DataSet("SDO_HMI_M", "SDO", "HMI", telescope="Magnetogram", name="SDO / HMI magnetogram"),
    DataSet("SDO_AIA", "SDO", "AIA", name="SDO / AIA"),
    DataSet("SOHO_MDI_I", "SoHO", "MDI", telescope="Continuum", name="SoHO / MDI continuum"),
    DataSet("SOHO_MDI_M", "SoHO", "MDI", telescope="Magnetogram", name="SoHO / MDI magnetogram"),
    DataSet("SOHO_EIT", "SoHO", "EIT", name="SoHO / EIT"),
    DataSet("NANCAY_RH", "Nancay", "Radioheliograph", name="Nançay / Radioheliograph"),
    DataSet(
        "MEUDON_SH_HA",
        "Meudon",
        "Spectroheliograph",
        wavename="Halpha",
        table=PP_HFC_TABLE,
        name="Meudon / Spectroheliograph Hα",
    ),
    DataSet(
        "MEUDON_SH_K3",
        "Meudon",
        "Spectroheliograph",
        wavename="CAII K3",
        table=PP_HFC_TABLE,
        name="Meudon / Spectroheliograph Ca II K3",
    ),
)

# Default input arguments: the most recent SDO/AIA observation at the current
# date and time, with the active regions and the coronal holes
OBSERVATORY = "SDO"
INSTRUMENT = "AIA"
TELESCOPE = ""
WAVENAME = ""
FEATURE_KEYS = ("ar", "ch")


# ________________ Global Functions __________


def input_date(date: datetime) -> str:
    return date.strftime(HQI_TFORMAT)


def display_date(value: Any) -> str:
    """Format a date of observation for display, e.g. "2012-06-01 12:00:00 UTC"."""
    try:
        return to_datetime(value).strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError):
        return str(value)


#: Display of the wavelength units of the HFC
WAVE_UNITS = {"NM": "nm", "A": "Å", "ANGSTROM": "Å", "UM": "µm", "MM": "mm", "CM": "cm", "M": "m"}
SPEED_OF_LIGHT = 299_792_458.0  # m/s


def wavelength_text(wavemin: Any, waveunit: Any) -> str:
    """Format a wavelength for display, e.g. "17.1 nm" or "1.999 m (150 MHz)"."""
    unit_key = str(waveunit or "").strip().upper()
    unit = WAVE_UNITS.get(unit_key, str(waveunit or "").strip())
    try:
        value = float(wavemin)
    except (TypeError, ValueError):
        return f"{wavemin} {unit}".strip()
    text = f"{value:.4g} {unit}".strip()
    if unit_key == "M" and value > 0:
        # radio observations: also give the frequency
        text += f" ({SPEED_OF_LIGHT / value / 1e6:.0f} MHz)"
    return text


def parse_features(text: str) -> list[str]:
    """Parse a comma-separated list of feature keys (e.g. "ar,ch"; "" for none)."""
    keys = [key.strip().lower() for key in text.split(",") if key.strip()]
    unknown = [key for key in keys if key not in FEATURE_BY_KEY]
    if unknown:
        known = ", ".join(FEATURE_BY_KEY)
        raise ValueError(f"Unknown feature(s): {', '.join(unknown)} (known: {known})")
    return keys


def find_dataset(
    observatory: str, instrument: str, telescope: str = "", wavename: str = ""
) -> int | None:
    """Return the index in DATASETS matching the input arguments, if any.

    When several data sets match the observatory and the instrument, the
    telescope and the wavename are used to choose between them; by default
    the first one is returned.
    """
    candidates = [
        i
        for i, ds in enumerate(DATASETS)
        if ds.observatory.lower() == observatory.lower().strip()
        and ds.instrument.lower() == instrument.lower().strip()
    ]
    for attr, value in (("telescope", telescope), ("wavename", wavename)):
        value = (value or "").lower().strip()
        if not value:
            continue
        matching = [i for i in candidates if getattr(DATASETS[i], attr).lower() == value]
        if matching:
            candidates = matching
    return candidates[0] if candidates else None


DIRECTIONS = ("nearest", "latest", "previous", "next")


def load_observation(
    hqi: HQIClient, dataset: DataSet, date: datetime, direction: str = "nearest"
) -> Row | None:
    """Return an observation of a data set, relatively to a date.

    ``direction`` is either "nearest" (the observation nearest to the date),
    "latest" (the most recent observation at the date, i.e. at or before it),
    "previous" (the last one strictly before the date) or "next" (the first one
    strictly after the date).
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"Unknown direction: {direction}")
    if direction == "latest":
        response = hqi.select(
            dataset.table,
            what=OBS_FIELDS,
            where=and_conditions(dataset.where(), sql_where({"DATE_OBS": (None, date)})),
            order_by="DATE_OBS DESC",
            limit=1,
        )
        return response.first()
    method = getattr(hqi, direction)
    row: Row | None = method(dataset.table, date, what=OBS_FIELDS, where=dataset.where())
    return row


def feature_query(feature: Feature, date: datetime) -> dict[str, Any]:
    """Build the parameters of HQIClient.select to get features observed around a date."""
    return {
        "table": feature.table,
        "what": FEATURE_FIELDS,
        "where": {"DATE_OBS": (date - FEATURE_TIME_WINDOW, date + FEATURE_TIME_WINDOW)},
    }


def closest_rows(rows: Sequence[Row], date: datetime) -> list[Row]:
    """Keep only the rows whose DATE_OBS is the closest to ``date``."""
    if not rows:
        return []
    deltas = [abs(to_datetime(row["DATE_OBS"]) - date) for row in rows]
    dt_min = min(deltas)
    return [row for row, dt in zip(rows, deltas, strict=True) if dt == dt_min]


def track_color(track_id: int) -> tuple[float, float, float]:
    """Return a color identifying a feature tracking id."""
    track_id = (5000 * track_id) % 16777216  # (256*256*256)
    r = track_id % 256
    g = track_id // 256 % 256
    b = track_id // 65536 % 256
    return r / 256.0, g / 256.0, b / 256.0


def feature_contour(row: Row) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
    """Return the contour (in arcsec) of a feature, or None if not available."""
    try:
        cdelt1 = float(row["CDELT1"])
        cdelt2 = float(row["CDELT2"])
        crpix1 = float(row["CENTER_X"])
        crpix2 = float(row["CENTER_Y"])
        start = [int(row["CC_X_PIX"]), int(row["CC_Y_PIX"])]
        xs, ys = chain2image(str(row["CC"]), start)
    except (KeyError, TypeError, ValueError):
        # e.g. prominences, which have no chain code in pixels
        return None
    x_arcsec = cdelt1 * (np.asarray(xs, dtype=np.float64) - crpix1)
    y_arcsec = cdelt2 * (np.asarray(ys, dtype=np.float64) - crpix2)
    return x_arcsec, y_arcsec


def image_to_array(image: Image.Image) -> NDArray[Any]:
    """Convert a quicklook image to an array suitable for imshow."""
    if image.mode not in ("L", "RGB", "RGBA"):
        image = image.convert("L")
    data = np.flipud(np.asarray(image))
    if data.ndim == 2:
        return auto_contrast(data, low=0.0, high=1.0)
    return data


# ________________ Class Definition __________


class Viewer(tk.Frame):
    """Main window of the HFC viewer."""

    def __init__(
        self,
        master: tk.Tk,
        date: str | None = None,
        observatory: str = OBSERVATORY,
        instrument: str = INSTRUMENT,
        telescope: str = TELESCOPE,
        wavename: str = WAVENAME,
        url_wsdl: str = URL_WSDL,
        xsize: int | None = None,
        ysize: int | None = None,
        dev: bool = False,
        features: Sequence[str] = FEATURE_KEYS,
    ) -> None:
        super().__init__(master, background=theme.WHITE)
        self.master: tk.Tk = master
        self._fonts = theme.apply_theme(master)
        # The HFC values are kept as strings, as returned by the service
        self._hqi = HQIClient(URL_WSDL_DEV if dev else url_wsdl, typed=False)

        self._date = tk.StringVar(value=date or input_date(datetime.now()))
        self._obsid = tk.IntVar()
        index = find_dataset(observatory, instrument, telescope, wavename)
        if index is None:
            messagebox.showerror("ERROR", "UNKNOWN OBSERVATORY/INSTRUMENT!")
            index = find_dataset(OBSERVATORY, INSTRUMENT) or 0
        self._obsid.set(index)

        width = xsize or int(0.7 * master.winfo_screenwidth())
        height = ysize or int(0.8 * master.winfo_screenheight())
        self.master.geometry(f"{width}x{height}")
        self.master.minsize(960, 640)
        self.master.configure(background=theme.WHITE)

        # Feature check buttons states, and number of contours displayed
        self._feat_on = {
            feature.key: tk.IntVar(value=int(feature.key in features)) for feature in FEATURES
        }
        self._feat_count = {feature.key: tk.StringVar() for feature in FEATURES}
        # Feature contour color table (0: by feature, 1: by tracking)
        self._feat_ct = tk.IntVar(value=0)
        self._status = tk.StringVar()

        self.obs_data: Row | None = None
        self.image: Image.Image | None = None
        # quicklook image ready to be displayed (computed once per observation)
        self._image_array: NDArray[Any] | None = None
        self._feat_data: dict[str, list[Row] | None] = {}
        self._feat_artists: list[Any] = []
        self._date_text: Any = None
        self._xlim: tuple[float, float] = (0.0, 0.0)
        self._ylim: tuple[float, float] = (0.0, 0.0)

        self._build_menubar()
        self.master.config(menu=self._menubar)
        self._place_widgets()

        # Load and plot the observation nearest to the given date or, by default,
        # the most recent observation at the current date and time
        if date:
            self._set_date()
        else:
            self._latest_date()

    @property
    def dataset(self) -> DataSet:
        return DATASETS[self._obsid.get()]

    def _build_menubar(self) -> None:
        self._menubar = tk.Menu(self.master)
        filemenu = tk.Menu(self._menubar, tearoff=0)
        filemenu.add_command(label="Quit", command=self.master.quit)
        self._menubar.add_cascade(label="File", menu=filemenu)

        optmenu = tk.Menu(self._menubar, tearoff=0)
        colmenu = tk.Menu(optmenu, tearoff=0)
        colmenu.add_radiobutton(
            label="Colors by tracking", variable=self._feat_ct, value=1, command=self._draw_features
        )
        colmenu.add_radiobutton(
            label="Colors by feature", variable=self._feat_ct, value=0, command=self._draw_features
        )
        optmenu.add_cascade(label="Set colors", menu=colmenu)
        self._menubar.add_cascade(label="Options", menu=optmenu)

        helpmenu = tk.Menu(self._menubar, tearoff=0)
        helpmenu.add_command(label="Help", command=self._show_help)
        helpmenu.add_command(label="About HFC Viewer", command=self._about)
        self._menubar.add_cascade(label="Help", menu=helpmenu)

    # ________________ Widgets _______________________

    def _place_widgets(self) -> None:
        self._place_header()
        self._place_navigation()
        self._place_status_bar()
        body = ttk.Frame(self)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self._place_side_panel(body)
        self._place_plot(body)

    def _place_header(self) -> None:
        """Anthracite band with a violet brand block, as on the LIRA website."""
        header = ttk.Frame(self, style="Header.TFrame")
        header.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(header, text="HFC", style="Brand.TLabel", padding=(18, 12)).pack(
            side=tk.LEFT, fill=tk.Y
        )
        ttk.Label(header, text="HFC Viewer", style="Header.TLabel", padding=(16, 8, 10, 8)).pack(
            side=tk.LEFT
        )
        ttk.Label(header, text="Heliophysics Feature Catalogue", style="Subheader.TLabel").pack(
            side=tk.LEFT, pady=(4, 0)
        )
        ttk.Frame(self, style="Accent.TFrame", height=4).pack(side=tk.TOP, fill=tk.X)

    def _place_navigation(self) -> None:
        nav = ttk.Frame(self, padding=(16, 10))
        nav.pack(side=tk.TOP, fill=tk.X)
        self._prev_btn = ttk.Button(
            nav, text="‹  Previous", style="Secondary.TButton", command=self._prev_date
        )
        self._prev_btn.pack(side=tk.LEFT)
        ttk.Label(nav, text="Date (UTC)", style="Field.TLabel").pack(side=tk.LEFT, padx=(16, 6))
        self._header = ttk.Entry(nav, textvariable=self._date, width=20, font=self._fonts.mono)
        self._header.pack(side=tk.LEFT, ipady=2)
        self._header.bind("<Return>", self._date_event)
        self._next_btn = ttk.Button(
            nav, text="Next  ›", style="Secondary.TButton", command=self._next_date
        )
        self._next_btn.pack(side=tk.LEFT, padx=(10, 0))
        # Most recent observation at the current date and time
        self._latest_btn = ttk.Button(nav, text="Latest", command=self._latest_date)
        self._latest_btn.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(
            nav, text="Format: YYYY-MM-DDTHH:MM:SS, then press Return", style="Field.TLabel"
        ).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Separator(self, orient=tk.HORIZONTAL).pack(side=tk.TOP, fill=tk.X)

    def _place_status_bar(self) -> None:
        bar = ttk.Frame(self, style="Status.TFrame", padding=(16, 6))
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bar, textvariable=self._status, style="Status.TLabel").pack(side=tk.LEFT)
        ttk.Label(bar, text=f"pyhfc {__version__}", style="Status.TLabel").pack(side=tk.RIGHT)

    def _section(self, parent: tk.Misc, text: str, top: int = 0) -> None:
        ttk.Label(parent, text=text, style="Section.TLabel").pack(anchor=tk.W, pady=(top, 2))
        ttk.Frame(parent, style="Accent.TFrame", height=2).pack(fill=tk.X, pady=(0, 6))

    def _place_side_panel(self, body: ttk.Frame) -> None:
        side = ttk.Frame(body, style="Side.TFrame", padding=(18, 14))
        side.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Separator(body, orient=tk.VERTICAL).pack(side=tk.RIGHT, fill=tk.Y)

        self._section(side, "DATA SETS")
        for index, dataset in enumerate(DATASETS):
            ttk.Radiobutton(
                side,
                text=dataset.display,
                value=index,
                variable=self._obsid,
                command=self._set_date,
                style="Side.TRadiobutton",
            ).pack(anchor=tk.W, fill=tk.X)

        self._section(side, "FEATURES", top=14)
        for feature in FEATURES:
            row = ttk.Frame(side, style="Side.TFrame")
            row.pack(fill=tk.X)
            ttk.Checkbutton(
                row,
                text=feature.label,
                variable=self._feat_on[feature.key],
                command=self._draw_features,
                style="Side.TCheckbutton",
            ).pack(side=tk.LEFT)
            ttk.Label(row, textvariable=self._feat_count[feature.key], style="Count.TLabel").pack(
                side=tk.RIGHT, padx=(6, 0)
            )
            # legend: a sample of the contour line
            swatch = tk.Canvas(
                row, width=26, height=14, background=theme.VIOLET_PALE, highlightthickness=0
            )
            swatch.create_line(2, 7, 24, 7, fill=theme.NIGHT, width=5, capstyle=tk.ROUND)
            swatch.create_line(2, 7, 24, 7, fill=feature.color, width=3, capstyle=tk.ROUND)
            swatch.pack(side=tk.RIGHT, padx=(10, 0))

        self._section(side, "CONTOUR COLORS", top=14)
        row = ttk.Frame(side, style="Side.TFrame")
        row.pack(fill=tk.X)
        for value, text in ((0, "By feature"), (1, "By tracking")):
            ttk.Radiobutton(
                row,
                text=text,
                value=value,
                variable=self._feat_ct,
                command=self._draw_features,
                style="Side.TRadiobutton",
            ).pack(side=tk.LEFT, padx=(0, 16))

    def _place_plot(self, body: ttk.Frame) -> None:
        frame = ttk.Frame(body, padding=(8, 8, 8, 0))
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._fig = Figure(figsize=(6, 6), dpi=100, layout="constrained", facecolor=theme.WHITE)
        self._plt = self._fig.add_subplot(111)
        self._canvas = FigureCanvasTkAgg(self._fig, master=frame)
        toolbar = NavigationToolbar2Tk(self._canvas, frame, pack_toolbar=False)
        for widget in (toolbar, *toolbar.winfo_children()):
            with contextlib.suppress(tk.TclError):  # widgets without background
                widget["background"] = theme.WHITE
        toolbar.update()
        toolbar.pack(side=tk.BOTTOM, fill=tk.X)
        canvas = self._canvas.get_tk_widget()
        canvas.configure(background=theme.WHITE, highlightthickness=0)
        canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    # ________________ Navigation ____________________

    def _date_event(self, event: tk.Event[ttk.Entry]) -> None:
        self._set_date()

    def _set_date(self) -> None:
        self._load_observation("nearest")

    def _prev_date(self) -> None:
        logger.info("Loading previous date...")
        self._load_observation("previous")

    def _next_date(self) -> None:
        logger.info("Loading next date...")
        self._load_observation("next")

    def _latest_date(self) -> None:
        """Load the most recent observation at the current date and time."""
        logger.info("Loading the most recent observation...")
        self._date.set(input_date(datetime.now()))
        self._load_observation("latest")

    def _current_date(self) -> datetime | None:
        date_obs = self._date.get().strip()
        if DATE_PATTERN.match(date_obs) is None:
            messagebox.showerror(
                "ERROR", "INPUT DATE FORMAT IS INCORRECT!\n(expected YYYY-MM-DDTHH:MM:SS)"
            )
            return None
        try:
            return datetime.strptime(date_obs, HQI_TFORMAT)
        except ValueError:
            messagebox.showerror("ERROR", "INPUT DATE IS INVALID!")
            return None

    def _busy(self, func: Callable[[], Any], message: str = "Loading…") -> Any:
        """Run ``func`` showing a busy cursor and a message in the status bar."""
        previous = self._status.get()
        self._status.set(message)
        self.master.config(cursor="watch")
        self.master.update_idletasks()
        try:
            return func()
        finally:
            self.master.config(cursor="")
            self._status.set(previous)

    def _load_observation(self, direction: str) -> None:
        date_obs = self._current_date()
        if date_obs is None:
            return
        dataset = self.dataset
        logger.info(
            "Loading information for the data set %s (DATE_OBS=%s, direction=%s)",
            dataset.title,
            input_date(date_obs),
            direction,
        )
        try:
            row = self._busy(
                lambda: load_observation(self._hqi, dataset, date_obs, direction),
                f"Loading {dataset.display} observation…",
            )
        except HQIError as err:
            logger.error("Querying HFC has failed: %s", err)
            self._status.set("Querying the HFC has failed")
            messagebox.showerror("ERROR", "QUERYING HFC HAS FAILED!")
            return
        if row is None:
            self._status.set(f"No {dataset.display} observation found")
            messagebox.showwarning("WARNING", "NO DATA FOUND IN THE HFC!")
            return

        self.obs_data = row
        self._date.set(str(row["DATE_OBS"]))
        self._feat_data = {}
        self._load_qclk()
        self._plot_qclk()

    def _load_qclk(self) -> None:
        if self.obs_data is None:
            return
        qclk_url = f"{self.obs_data['QCLK_URL']}/{self.obs_data['QCLK_FNAME']}"
        logger.info("Loading quicklook image from %s", qclk_url)
        self.image = self._busy(lambda: load_image(qclk_url), "Loading the quicklook image…")
        # processed once here, not at each redraw
        self._image_array = image_to_array(self.image) if self.image is not None else None

    # ________________ Plot __________________________

    def _plot_qclk(self) -> None:
        """Draw the observation and the selected features."""
        if self.obs_data is None:
            return
        self._draw_observation()
        self._draw_features()

    def _draw_observation(self) -> None:
        """Draw the quicklook image of the observation (or the solar limb)."""
        if self.obs_data is None:
            return
        data = self.obs_data
        ax = self._plt
        ax.clear()
        self._feat_artists = []
        r_sun = float(data["R_SUN"])
        naxis1 = int(data["NAXIS1"])
        naxis2 = int(data["NAXIS2"])
        cdelt1 = float(data["CDELT1"])
        cdelt2 = float(data["CDELT2"])
        crpix1 = float(data["CENTER_X"])
        crpix2 = float(data["CENTER_Y"])

        logger.info("Plotting quicklook image")
        # X and Y axis (in arcsec)
        xs = cdelt1 * (np.arange(naxis1) - crpix1)
        ys = cdelt2 * (np.arange(naxis2) - crpix2)
        self._xlim = (float(xs.min()), float(xs.max()))
        self._ylim = (float(ys.min()), float(ys.max()))

        ax.set_facecolor(theme.NIGHT)
        if self._image_array is None:
            logger.warning("NO QUICKLOOK IMAGE FOUND!")
            # If no image --> plot solar radius contour
            theta = np.linspace(0.0, 2.0 * np.pi, 361)
            ax.plot(
                cdelt1 * r_sun * np.cos(theta),
                cdelt2 * r_sun * np.sin(theta),
                color=theme.VIOLET_LIGHT,
            )
        else:
            ax.imshow(
                self._image_array,
                cmap="gray",
                extent=(*self._xlim, *self._ylim),
                origin="lower",
            )
        # title, and the date of observation on a second line (long titles do not overlap it)
        title = f"{self.dataset.display}  ·  {wavelength_text(data['WAVEMIN'], data['WAVEUNIT'])}"
        ax.set_title(title, loc="left", fontsize=14, fontweight="bold", color=theme.INK, pad=26)
        self._date_text = ax.text(
            0.0,
            1.012,
            display_date(data["DATE_OBS"]),
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=12,
            color=theme.MUTED,
        )
        ax.set_xlabel("X  [arcsec]", fontsize=12, color=theme.INK)
        ax.set_ylabel("Y  [arcsec]", fontsize=12, color=theme.INK)
        ax.tick_params(colors=theme.INK, labelsize=11)
        for spine in ax.spines.values():
            spine.set_color(theme.MUTED)

    def _draw_features(self) -> None:
        """(Re)draw the contours of the selected features, keeping the image."""
        if self.obs_data is None:
            return
        for artist in self._feat_artists:
            artist.remove()
        self._feat_artists = []
        for feature in FEATURES:
            count = self._feat_count[feature.key]
            if self._feat_on[feature.key].get():
                logger.info("Plotting %s data", feature.label.lower())
                number = self._plot_feat(feature)
                count.set(str(number) if number else "none")
            else:
                count.set("")
        self._plt.set_xlim(*self._xlim)
        self._plt.set_ylim(*self._ylim)
        self._update_status()
        self._canvas.draw_idle()

    def _plot_feat(self, feature: Feature) -> int:
        """Draw the contours of a feature, and return their number."""
        if feature.key not in self._feat_data:
            self._feat_data[feature.key] = self._busy(
                lambda: self._load_feat(feature), f"Loading the {feature.label.lower()}…"
            )
        feat_data = self._feat_data[feature.key]
        if not feat_data:
            return 0

        by_tracking = self._feat_ct.get() == 1
        # dark outline, so that the contours are visible on any part of the image
        outline = [
            patheffects.Stroke(linewidth=3.4, foreground=theme.NIGHT, alpha=0.8),
            patheffects.Normal(),
        ]
        number = 0
        for row in feat_data:
            contour = feature_contour(row)
            if contour is None:
                continue
            color: str | tuple[float, float, float] = feature.color
            try:
                track_id = int(row["TRACK_ID"])
            except (KeyError, TypeError, ValueError):
                track_id = 0
            if by_tracking and track_id > 0:
                color = track_color(track_id)
            self._feat_artists += self._plt.plot(
                *contour, color=color, linewidth=1.8, path_effects=outline
            )
            number += 1
        return number

    def _update_status(self) -> None:
        if self.obs_data is None:
            return
        data = self.obs_data
        parts = [
            self.dataset.display,
            wavelength_text(data["WAVEMIN"], data["WAVEUNIT"]),
            display_date(data["DATE_OBS"]),
        ]
        if self._image_array is None:
            parts.append("no quicklook image")
        for feature in FEATURES:
            count = self._feat_count[feature.key].get()
            if count:
                number = "no" if count == "none" else count
                parts.append(f"{number} {feature.label.lower()}")
        self._status.set("   ·   ".join(parts))

    def _load_feat(self, feature: Feature) -> list[Row] | None:
        date_obs = self._current_date()
        if date_obs is None:
            return None
        try:
            response = self._hqi.select(**feature_query(feature, date_obs))
        except HQIError as err:
            logger.error("Querying HFC has failed: %s", err)
            messagebox.showerror("ERROR", "QUERYING HFC HAS FAILED!")
            return None
        rows = closest_rows(response.rows, date_obs)
        if not rows:
            logger.warning("No %s data found around this date in the HFC!", feature.label)
            return None
        logger.info("HFC %s data found for the date %s", feature.label, rows[0]["DATE_OBS"])
        return rows

    def _show_help(self) -> None:
        msg = (
            "Enter a date (YYYY-MM-DDTHH:MM:SS) and press Return to load\n"
            "the nearest observation of the selected data set.\n"
            "\n"
            "Use Previous/Next to browse the observations,\n"
            "and the FEATURES check buttons to overplot\n"
            "the features detected around this date."
        )
        messagebox.showinfo("HFC Viewer help", msg)

    def _about(self) -> None:
        msg = (
            f"HFC Viewer {__version__}\n"
            "\n"
            "HFC Viewer for Python is developed and\n"
            "maintained by LESIA-Observatoire de Paris.\n"
            "\n"
            "More information about available data\n"
            "can be found on the HFC web page:\n"
            "http://voparis-helio.obspm.fr/hfc-gui/\n"
            "\n"
            "The Heliophysics Feature Catalogue (HFC)\n"
            "is a service of the HELIO virtual observatory:\n"
            "http://www.helio-vo.eu/\n"
            "\n"
            "Any feedback is welcome, please send your "
            "comments to xavier dot bonnin at obspm dot fr."
        )
        messagebox.showinfo("HFC Viewer", msg)


# ________________ Main __________________________


def _features_arg(text: str) -> list[str]:
    try:
        return parse_features(text)
    except ValueError as err:
        raise argparse.ArgumentTypeError(str(err)) from err


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="hfcviewer", description=__doc__)
    parser.add_argument(
        "-d",
        "--date",
        help=(
            "Date of observation (YYYY-MM-DDTHH:MM:SS); the observation nearest to this "
            "date is displayed (default: the most recent one at the current date and time)"
        ),
    )
    parser.add_argument("-o", "--observatory", default=OBSERVATORY, help="Name of the observatory")
    parser.add_argument("-i", "--instrument", default=INSTRUMENT, help="Name of the instrument")
    parser.add_argument("-t", "--telescope", default=TELESCOPE, help="Name of the telescope")
    parser.add_argument("-w", "--wavename", default=WAVENAME, help="Name of the wavename")
    parser.add_argument(
        "-f",
        "--features",
        type=_features_arg,
        default=list(FEATURE_KEYS),
        help=(
            "Comma-separated features to display "
            f"({', '.join(FEATURE_BY_KEY)}; default: {','.join(FEATURE_KEYS)}; '' for none)"
        ),
    )
    parser.add_argument("-u", "--url_wsdl", default=URL_WSDL, help="Url of the wsdl file to load")
    parser.add_argument("-x", "--xsize", type=int, help="Window width on screen in pixels")
    parser.add_argument("-y", "--ysize", type=int, help="Window height on screen in pixels")
    parser.add_argument("-Q", "--quiet", action="store_true", help="Quiet mode")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug mode")
    parser.add_argument(
        "-D", "--dev", action="store_true", help="Use the development version of the HFC service"
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    level = logging.WARNING if args.quiet else logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)-8s: %(message)s")
    # suds is very verbose
    logging.getLogger("suds").setLevel(logging.WARNING)

    root = tk.Tk()
    root.title("HFC Viewer")
    viewer = Viewer(
        master=root,
        date=args.date,
        observatory=args.observatory,
        instrument=args.instrument,
        telescope=args.telescope,
        wavename=args.wavename,
        url_wsdl=args.url_wsdl,
        xsize=args.xsize,
        ysize=args.ysize,
        dev=args.dev,
        features=args.features,
    )
    viewer.pack(expand=True, fill="both")
    root.mainloop()


if __name__ == "__main__":
    main()
