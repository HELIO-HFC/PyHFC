# SPDX-License-Identifier: EUPL-1.2
"""Graphical theme of the HFC viewer, inspired by the LIRA visual identity.

LIRA (Laboratoire d'Instrumentation et de Recherche en Astrophysique,
https://lira.obspm.fr/): anthracite and white, with a violet accent, flat
surfaces and a geometric sans-serif typeface.
"""

from __future__ import annotations

import logging
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from importlib.resources import files
from tkinter import ttk

from PIL import Image, ImageTk

logger = logging.getLogger(__name__)

#: Logo of the LIRA, displayed in the header of the viewer
LOGO = "lira_logo.png"

# ________________ Colors (LIRA palette) _________

INK = "#292929"  # LIRA text and header
NIGHT = "#131A20"  # LIRA dark surfaces (plot background)
WHITE = "#FFFFFF"
VIOLET = "#8D6DFF"  # LIRA accent
VIOLET_DARK = "#6A4BE8"  # buttons (contrast with white text >= 4.5:1)
VIOLET_DARKER = "#5434CF"  # pressed buttons
VIOLET_LIGHT = "#C2B6FE"
VIOLET_PALE = "#F4F0FF"
TEAL = "#00A599"  # LIRA secondary accent
GREY_LINE = "#E1DCF5"
MUTED = "#5C5C66"  # secondary text (contrast with white >= 6:1)

#: Colors of the feature contours: saturated, to be visible on the dark
#: and light parts of the solar images (contours also have a dark outline).
FEATURE_COLORS = {
    "ar": "#FF5A5F",  # active regions
    "ch": "#6D96FF",  # coronal holes (LIRA blue)
    "sp": "#FFD23F",  # sunspots
    "rs": "#D66DFF",  # radio sources (LIRA magenta)
    "pr": "#3DDC97",  # prominences
    "fi": "#00C8FF",  # filaments
}

# Geometric sans-serif typefaces, closest to the LIRA ones first
FONT_FAMILIES = (
    "Avenir Next",
    "Century Gothic",
    "Avenir",
    "Helvetica Neue",
    "Noto Sans",
    "DejaVu Sans",
    "Segoe UI",
    "Helvetica",
    "Arial",
)
MONO_FAMILIES = ("Menlo", "DejaVu Sans Mono", "Consolas", "Courier New", "Courier")


@dataclass(frozen=True)
class Fonts:
    """Fonts of the viewer."""

    base: tuple[str, int]
    small: tuple[str, int]
    bold: tuple[str, int, str]
    section: tuple[str, int, str]
    title: tuple[str, int, str]
    brand: tuple[str, int, str]
    mono: tuple[str, int]


def _first_available(root: tk.Misc, families: tuple[str, ...]) -> str:
    available = set(tkfont.families(root))
    return next((family for family in families if family in available), "TkDefaultFont")


def make_fonts(root: tk.Misc) -> Fonts:
    """Return the fonts of the viewer, with the typefaces available on the system."""
    family = _first_available(root, FONT_FAMILIES)
    mono = _first_available(root, MONO_FAMILIES)
    return Fonts(
        base=(family, 13),
        small=(family, 11),
        bold=(family, 13, "bold"),
        section=(family, 11, "bold"),
        title=(family, 18, "bold"),
        brand=(family, 15, "bold"),
        mono=(mono, 13),
    )


def apply_theme(root: tk.Misc) -> Fonts:
    """Configure the ttk styles of the viewer, and return its fonts."""
    fonts = make_fonts(root)
    style = ttk.Style(root)
    # "clam" can be fully styled on every platform (unlike "aqua" on macOS)
    style.theme_use("clam")

    style.configure(".", background=WHITE, foreground=INK, font=fonts.base)
    style.configure("TFrame", background=WHITE)
    style.configure("Side.TFrame", background=VIOLET_PALE)
    style.configure("Header.TFrame", background=INK)
    style.configure("Accent.TFrame", background=VIOLET)
    style.configure("Brand.TFrame", background=VIOLET)
    style.configure("Status.TFrame", background=VIOLET_PALE)

    style.configure("TLabel", background=WHITE, foreground=INK, font=fonts.base)
    style.configure("Header.TLabel", background=INK, foreground=WHITE, font=fonts.title)
    style.configure("Subheader.TLabel", background=INK, foreground=VIOLET_LIGHT, font=fonts.base)
    style.configure("Brand.TLabel", background=VIOLET, foreground=WHITE, font=fonts.brand)
    style.configure("Field.TLabel", background=WHITE, foreground=MUTED, font=fonts.small)
    style.configure(
        "Section.TLabel", background=VIOLET_PALE, foreground=VIOLET_DARK, font=fonts.section
    )
    style.configure("Side.TLabel", background=VIOLET_PALE, foreground=INK, font=fonts.base)
    style.configure("Count.TLabel", background=VIOLET_PALE, foreground=MUTED, font=fonts.small)
    style.configure("Status.TLabel", background=VIOLET_PALE, foreground=INK, font=fonts.small)

    # Buttons: violet, flat, with a darker shade when hovered/pressed
    style.configure(
        "TButton",
        background=VIOLET_DARK,
        foreground=WHITE,
        font=fonts.bold,
        borderwidth=0,
        focusthickness=2,
        focuscolor=VIOLET_LIGHT,
        padding=(14, 6),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[("pressed", VIOLET_DARKER), ("active", VIOLET_DARKER), ("disabled", MUTED)],
        foreground=[("disabled", VIOLET_PALE)],
    )
    # Secondary buttons: white with a violet border and text
    style.configure(
        "Secondary.TButton",
        background=WHITE,
        foreground=VIOLET_DARK,
        bordercolor=VIOLET_DARK,
        lightcolor=VIOLET_DARK,
        darkcolor=VIOLET_DARK,
        borderwidth=2,
        relief="solid",
    )
    style.map(
        "Secondary.TButton",
        background=[("pressed", VIOLET_LIGHT), ("active", VIOLET_PALE)],
        foreground=[("pressed", VIOLET_DARKER), ("active", VIOLET_DARKER)],
    )

    style.configure(
        "TEntry",
        fieldbackground=WHITE,
        foreground=INK,
        bordercolor=VIOLET_LIGHT,
        lightcolor=VIOLET_LIGHT,
        darkcolor=VIOLET_LIGHT,
        padding=(8, 5),
        insertcolor=INK,
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", VIOLET_DARK)],
        lightcolor=[("focus", VIOLET_DARK)],
        darkcolor=[("focus", VIOLET_DARK)],
    )

    for widget in ("TRadiobutton", "TCheckbutton"):
        style.configure(
            f"Side.{widget}",
            background=VIOLET_PALE,
            foreground=INK,
            font=fonts.base,
            padding=(2, 2),
            indicatorsize=16,
            indicatordiameter=16,
            indicatorbackground=WHITE,
            indicatorforeground=WHITE,
            indicatormargin=(0, 0, 8, 0),
            upperbordercolor=VIOLET_DARK,
            lowerbordercolor=VIOLET_DARK,
            focuscolor=VIOLET_PALE,
        )
        style.map(
            f"Side.{widget}",
            background=[("active", VIOLET_PALE)],
            indicatorbackground=[("selected", VIOLET_DARK), ("pressed", VIOLET_LIGHT)],
            foreground=[("active", VIOLET_DARKER)],
        )

    style.configure("TSeparator", background=GREY_LINE)
    return fonts


def load_logo(height: int, master: tk.Misc | None = None) -> ImageTk.PhotoImage | None:
    """Return the logo of the LIRA resized to ``height`` pixels, or None if not available."""
    try:
        with (files("pyhfc.hfcviewer") / "assets" / LOGO).open("rb") as file:
            image = Image.open(file).convert("RGB")
            image.load()
    except (OSError, ModuleNotFoundError) as err:
        logger.warning("Can not load the logo: %s", err)
        return None
    width = round(image.width * height / image.height)
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(image, master=master)
