# SPDX-License-Identifier: EUPL-1.2
"""Loading of the quicklook images referenced by the HFC."""

from __future__ import annotations

import io
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from PIL import Image

__all__ = ["load_image", "quicklook_url"]

logger = logging.getLogger(__name__)


def quicklook_url(row: Mapping[str, Any]) -> str | None:
    """Return the url of the quicklook image of a row (QCLK_URL/QCLK_FNAME)."""
    url = row.get("QCLK_URL")
    fname = row.get("QCLK_FNAME")
    if not url or not fname:
        return None
    return f"{str(url).rstrip('/')}/{fname}"


def load_image(file: str | Path, timeout: float = 30) -> Image.Image | None:
    """Load an image remotely (http, https, ftp) or locally.

    Return None if the image can not be loaded.
    """
    file = str(file)
    if file.startswith(("http:", "https:", "ftp:")):
        try:
            with urlopen(file, timeout=timeout) as response:
                source: io.BytesIO | Path = io.BytesIO(response.read())
        except (URLError, OSError) as err:
            logger.error("Can not load %s: %s", file, err)
            return None
    else:
        source = Path(file)
        if not source.is_file():
            logger.error("%s does not exist!", file)
            return None
    try:
        image = Image.open(source)
        image.load()
    except OSError as err:
        logger.error("Can not read image %s: %s", file, err)
        return None
    return image
