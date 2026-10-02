# SPDX-License-Identifier: EUPL-1.2
"""Client API of the HELIO Query Interface (HQI) of the Heliophysics Feature Catalogue (HFC).

This sub-package does not depend on the viewer (Tkinter, matplotlib): it can
be used on its own to query the HFC::

    from pyhfc.api import HQIClient

    hqi = HQIClient()
    print(hqi.tables())
    sunspots = hqi.features("sunspots", "2012-06-01T00:00:00", "2012-06-01T01:00:00")
    for row in sunspots:
        print(row["DATE_OBS"], row["FEAT_X_ARCSEC"], row["FEAT_Y_ARCSEC"])
"""

from pyhfc.api.client import (
    HQI_DEV_WSDL,
    HQI_WSDL,
    HQIClient,
    HQIConnectionError,
    HQIError,
    HQIQueryError,
)
from pyhfc.api.quicklook import load_image, quicklook_url
from pyhfc.api.sql import hqi_where, sql_where
from pyhfc.api.tables import FEATURE_TABLES, feature_table
from pyhfc.api.votable import Field, QueryResponse, Row, Table, parse_response

__all__ = [
    "FEATURE_TABLES",
    "HQI_DEV_WSDL",
    "HQI_WSDL",
    "Field",
    "HQIClient",
    "HQIConnectionError",
    "HQIError",
    "HQIQueryError",
    "QueryResponse",
    "Row",
    "Table",
    "feature_table",
    "hqi_where",
    "load_image",
    "parse_response",
    "quicklook_url",
    "sql_where",
]
