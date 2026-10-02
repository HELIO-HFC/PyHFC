# SPDX-License-Identifier: EUPL-1.2
"""Python viewer for the Heliophysics Feature Catalogue (HFC).

@author: Xavier Bonnin (LESIA)
"""

from __future__ import annotations

import argparse
import logging
import re
import tkinter as tk
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from tkinter import messagebox
from typing import Any

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from numpy.typing import NDArray
from PIL import Image

from pyhfc import __version__
from pyhfc.api import HQI_DEV_WSDL, HQI_WSDL, HQIClient, HQIError, Row, load_image
from pyhfc.api.sql import sql_equals, to_datetime
from pyhfc.api.tables import OBS_TABLE, PP_TABLE
from pyhfc.improlib import auto_contrast, chain2image

__author__ = "Xavier Bonnin"
__email__ = "xavier.bonnin@obspm.fr"
__project__ = "HELIO (FP7 project No. 238969)"
__institute__ = "LESIA"

logger = logging.getLogger(__name__)

# Background color
BG_COLOR = "#C7CBE4"

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
    Feature("ar", "Active regions", "VIEW_AR_HQI", "r"),
    Feature("ch", "Coronal holes", "VIEW_CH_HQI", "b"),
    Feature("sp", "Sunspots", "VIEW_SP_HQI", "y"),
    Feature("rs", "NRH sources", "VIEW_RS_HQI", "m"),
    Feature("pr", "Prominences", "VIEW_PRO_HQI", "g"),
    Feature("fi", "Filaments", "VIEW_FIL_HQI", "c"),
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

    @property
    def title(self) -> str:
        parts = (self.observatory, self.instrument, self.telescope, self.wavename)
        return "-".join(part for part in parts if part)

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
    DataSet("SDO_HMI_I", "SDO", "HMI", telescope="Continuum"),
    DataSet("SDO_HMI_M", "SDO", "HMI", telescope="Magnetogram"),
    DataSet("SDO_AIA", "SDO", "AIA"),
    DataSet("SOHO_MDI_I", "SoHO", "MDI", telescope="Continuum"),
    DataSet("SOHO_MDI_M", "SoHO", "MDI", telescope="Magnetogram"),
    DataSet("SOHO_EIT", "SoHO", "EIT"),
    DataSet("NANCAY_RH", "Nancay", "Radioheliograph"),
    DataSet("MEUDON_SH_HA", "Meudon", "Spectroheliograph", wavename="Halpha", table=PP_HFC_TABLE),
    DataSet("MEUDON_SH_K3", "Meudon", "Spectroheliograph", wavename="CAII K3", table=PP_HFC_TABLE),
)

# Default input arguments
OBSERVATORY = "Nancay"
INSTRUMENT = "Radioheliograph"
TELESCOPE = ""
WAVENAME = ""


# ________________ Global Functions __________


def input_date(date: datetime) -> str:
    return date.strftime(HQI_TFORMAT)


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


DIRECTIONS = ("nearest", "previous", "next")


def load_observation(
    hqi: HQIClient, dataset: DataSet, date: datetime, direction: str = "nearest"
) -> Row | None:
    """Return the observation of a data set nearest to/before/after a date.

    ``direction`` is either "nearest", "previous" or "next".
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"Unknown direction: {direction}")
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
    ) -> None:
        super().__init__(master)
        self.master: tk.Tk = master
        # The HFC values are kept as strings, as returned by the service
        self._hqi = HQIClient(URL_WSDL_DEV if dev else url_wsdl, typed=False)

        self._date = tk.StringVar(value=date or input_date(datetime.now()))
        self._obsid = tk.IntVar()
        index = find_dataset(observatory, instrument, telescope, wavename)
        if index is None:
            messagebox.showerror("ERROR", "UNKNOWN OBSERVATORY/INSTRUMENT!")
            index = find_dataset(OBSERVATORY, INSTRUMENT) or 0
        self._obsid.set(index)

        width = xsize or int(0.6 * master.winfo_screenwidth())
        height = ysize or int(0.7 * master.winfo_screenheight())
        self.master.geometry(f"{width}x{height}")

        # Feature check buttons states
        self._feat_on = {feature.key: tk.IntVar() for feature in FEATURES}
        # Feature contour color table (0: by feature, 1: by tracking)
        self._feat_ct = tk.IntVar(value=0)

        self.obs_data: Row | None = None
        self.image: Image.Image | None = None
        self._feat_data: dict[str, list[Row] | None] = {}
        self._xlim: tuple[float, float] = (0.0, 0.0)
        self._ylim: tuple[float, float] = (0.0, 0.0)

        self._build_menubar()
        self.master.config(menu=self._menubar, bg=BG_COLOR)
        self._place_widgets()

        self._set_date()  # load and plot observation for self._date

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
            label="Colors by tracking", variable=self._feat_ct, value=1, command=self._plot_qclk
        )
        colmenu.add_radiobutton(
            label="Colors by feature", variable=self._feat_ct, value=0, command=self._plot_qclk
        )
        optmenu.add_cascade(label="Set colors", menu=colmenu)
        self._menubar.add_cascade(label="Options", menu=optmenu)

        helpmenu = tk.Menu(self._menubar, tearoff=0)
        helpmenu.add_command(label="Help", command=self._show_help)
        helpmenu.add_command(label="About HFC Viewer", command=self._about)
        self._menubar.add_cascade(label="Help", menu=helpmenu)

    def _place_widgets(self) -> None:
        # header frame and its widgets
        hframe = tk.Frame(self.master, bg=BG_COLOR)
        lbtn = tk.Button(
            hframe,
            text="Previous",
            bg=BG_COLOR,
            highlightbackground=BG_COLOR,
            command=self._prev_date,
        )
        rbtn = tk.Button(
            hframe, text="Next", bg=BG_COLOR, highlightbackground=BG_COLOR, command=self._next_date
        )
        self._header = tk.Entry(hframe, highlightbackground=BG_COLOR, textvariable=self._date)
        self._header.bind("<Return>", self._date_event)

        # Image frame and the plot window
        iframe = tk.Frame(self.master, bg=BG_COLOR)
        self._fig = Figure(figsize=(5, 4), dpi=100)
        self._plt = self._fig.add_subplot(111)
        self._canvas = FigureCanvasTkAgg(self._fig, master=iframe)
        toolbar = NavigationToolbar2Tk(self._canvas, iframe)
        toolbar.update()

        # the option menu frame
        oframe = tk.Frame(self.master, bg=BG_COLOR)

        # Data set buttons
        dlabel = tk.Label(oframe, text="DATA SETS", bg=BG_COLOR)
        dframe = tk.Frame(oframe, bg=BG_COLOR, relief=tk.SUNKEN, bd=2)
        for index, dataset in enumerate(DATASETS):
            tk.Radiobutton(
                dframe,
                text=dataset.label,
                command=self._set_date,
                variable=self._obsid,
                value=index,
                bg=BG_COLOR,
            ).pack(anchor=tk.W)

        # Features buttons
        flabel = tk.Label(oframe, text="FEATURES", bg=BG_COLOR)
        fframe = tk.Frame(oframe, bg=BG_COLOR, relief=tk.SUNKEN, bd=2)
        for feature in FEATURES:
            tk.Checkbutton(
                fframe,
                text=feature.label,
                variable=self._feat_on[feature.key],
                bg=BG_COLOR,
                command=self._plot_qclk,
            ).pack(anchor=tk.W)

        # pack the widgets
        hframe.pack(side="top", pady=4, anchor=tk.CENTER)
        lbtn.grid()
        self._header.grid(column=1, row=0, padx=12)
        rbtn.grid(column=2, row=0)
        iframe.pack(expand=True, fill="both", side="left")
        oframe.pack(expand=False, fill="both", side="left")
        dlabel.pack(anchor=tk.CENTER, ipady=2)
        dframe.pack(expand=False, fill="both", side="top")
        flabel.pack(anchor=tk.CENTER, ipady=2)
        fframe.pack(expand=False, fill="both", side="top")
        self._canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    def _date_event(self, event: tk.Event[tk.Entry]) -> None:
        self._set_date()

    def _set_date(self) -> None:
        self._load_observation("nearest")

    def _prev_date(self) -> None:
        logger.info("Loading previous date...")
        self._load_observation("previous")

    def _next_date(self) -> None:
        logger.info("Loading next date...")
        self._load_observation("next")

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

    def _busy(self, func: Callable[[], Any]) -> Any:
        """Run ``func`` showing a busy cursor."""
        self.master.config(cursor="watch")
        self.master.update_idletasks()
        try:
            return func()
        finally:
            self.master.config(cursor="")

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
            row = self._busy(lambda: load_observation(self._hqi, dataset, date_obs, direction))
        except HQIError as err:
            logger.error("Querying HFC has failed: %s", err)
            messagebox.showerror("ERROR", "QUERYING HFC HAS FAILED!")
            return
        if row is None:
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
        self.image = self._busy(lambda: load_image(qclk_url))

    def _plot_qclk(self) -> None:
        if self.obs_data is None:
            return
        data = self.obs_data

        # Clear older data
        self._plt.clear()
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

        if self.image is None:
            logger.warning("NO QUICKLOOK IMAGE FOUND!")
            # If no image --> plot solar radius contour
            theta = np.linspace(0.0, 2.0 * np.pi, 361)
            self._plt.plot(cdelt1 * r_sun * np.cos(theta), cdelt2 * r_sun * np.sin(theta))
        else:
            self._plt.imshow(
                image_to_array(self.image),
                cmap="gray",
                extent=(*self._xlim, *self._ylim),
                origin="lower",
            )
        self._plt.set_title(f"{self.dataset.title} [{data['WAVEMIN']} {data['WAVEUNIT']}]")
        self._plt.set_xlabel("X (arcsec)")
        self._plt.set_ylabel("Y (arcsec)")

        for feature in FEATURES:
            if self._feat_on[feature.key].get():
                logger.info("Plotting %s data", feature.label.lower())
                self._plot_feat(feature)

        self._plt.set_xlim(*self._xlim)
        self._plt.set_ylim(*self._ylim)
        self._canvas.draw_idle()

    def _plot_feat(self, feature: Feature) -> None:
        if feature.key not in self._feat_data:
            self._feat_data[feature.key] = self._busy(lambda: self._load_feat(feature))
        feat_data = self._feat_data[feature.key]
        if not feat_data:
            return

        by_tracking = self._feat_ct.get() == 1
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
            self._plt.plot(*contour, color=color)

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


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="hfcviewer", description=__doc__)
    parser.add_argument(
        "-d", "--date", help="Date of observation (YYYY-MM-DDTHH:MM:SS, default: now)"
    )
    parser.add_argument("-o", "--observatory", default=OBSERVATORY, help="Name of the observatory")
    parser.add_argument("-i", "--instrument", default=INSTRUMENT, help="Name of the instrument")
    parser.add_argument("-t", "--telescope", default=TELESCOPE, help="Name of the telescope")
    parser.add_argument("-w", "--wavename", default=WAVENAME, help="Name of the wavename")
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
    )
    viewer.pack(expand=True, fill="both")
    root.mainloop()


if __name__ == "__main__":
    main()
