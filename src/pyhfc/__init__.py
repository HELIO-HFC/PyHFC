# SPDX-License-Identifier: EUPL-1.2
"""Python tools for the HELIO Heliophysics Feature Catalogue (HFC).

- :mod:`pyhfc.api`: client of the HELIO Query Interface (HQI) of the HFC;
- :mod:`pyhfc.hfcviewer`: graphical viewer of the HFC observations and features;
- :mod:`pyhfc.improlib`: image processing routines (e.g. chain codes decoding).
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pyhfc")
except PackageNotFoundError:  # pragma: no cover - package not installed
    __version__ = "unknown"
