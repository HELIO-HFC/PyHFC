# SPDX-License-Identifier: EUPL-1.2
"""Tables of the Heliophysics Feature Catalogue (HFC).

The complete list of the tables is returned by :meth:`HQIClient.tables`.
"""

from __future__ import annotations

__all__ = [
    "AR_TABLE",
    "CH_TABLE",
    "FEATURE_TABLES",
    "FI_TABLE",
    "FRC_TABLE",
    "OBS_TABLE",
    "PP_TABLE",
    "PRO_TABLE",
    "RS_TABLE",
    "SS_TABLE",
    "T2_TABLE",
    "T3_TABLE",
    "feature_table",
]

FRC_TABLE = "FRC_INFO"  # Feature recognition codes
OBS_TABLE = "VIEW_OBS_HQI"  # Observations
PP_TABLE = "VIEW_PP_HQI"  # Pre-processed observations
AR_TABLE = "VIEW_AR_HQI"  # Active regions
CH_TABLE = "VIEW_CH_HQI"  # Coronal holes
SS_TABLE = "VIEW_SP_HQI"  # Sunspots
FI_TABLE = "VIEW_FIL_HQI"  # Filaments
PRO_TABLE = "VIEW_PRO_HQI"  # Prominences
RS_TABLE = "VIEW_RS_HQI"  # Radio sources (Nancay Radioheliograph)
T3_TABLE = "VIEW_T3_HQI"  # Type III radio bursts
T2_TABLE = "VIEW_T2_HQI"  # Type II radio bursts

#: Feature names (and aliases) -> HFC table
FEATURE_TABLES = {
    "ar": AR_TABLE,
    "active_region": AR_TABLE,
    "ch": CH_TABLE,
    "coronal_hole": CH_TABLE,
    "sp": SS_TABLE,
    "ss": SS_TABLE,
    "sunspot": SS_TABLE,
    "fi": FI_TABLE,
    "fil": FI_TABLE,
    "filament": FI_TABLE,
    "pr": PRO_TABLE,
    "pro": PRO_TABLE,
    "prominence": PRO_TABLE,
    "rs": RS_TABLE,
    "radio_source": RS_TABLE,
    "t3": T3_TABLE,
    "type3": T3_TABLE,
    "type_iii": T3_TABLE,
    "typeiii": T3_TABLE,
    "t2": T2_TABLE,
    "type2": T2_TABLE,
    "type_ii": T2_TABLE,
    "typeii": T2_TABLE,
}


def feature_table(feature: str) -> str:
    """Return the HFC table of a feature (e.g. "ar", "sunspots", "Coronal holes").

    Raise ``KeyError`` for an unknown feature.
    """
    key = feature.lower().strip().replace(" ", "_").replace("-", "_")
    if key in FEATURE_TABLES:
        return FEATURE_TABLES[key]
    # plural forms, e.g. "sunspots", "active_regions"
    singular = key.removesuffix("s")
    if singular in FEATURE_TABLES:
        return FEATURE_TABLES[singular]
    raise KeyError(f"Unknown feature: {feature!r} (known: {', '.join(sorted(FEATURE_TABLES))})")
