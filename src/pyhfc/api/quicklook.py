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

__all__ = ["fetch_image", "is_remote", "load_image", "open_image", "quicklook_url"]

logger = logging.getLogger(__name__)


def quicklook_url(row: Mapping[str, Any]) -> str | None:
    """Return the url of the quicklook image of a row (QCLK_URL/QCLK_FNAME)."""
    url = row.get("QCLK_URL")
    fname = row.get("QCLK_FNAME")
    if not url or not fname:
        return None
    return f"{str(url).rstrip('/')}/{fname}"


def is_remote(file: str | Path) -> bool:
    """Return True if ``file`` is a remote url (http, https, ftp)."""
    return str(file).startswith(("http:", "https:", "ftp:"))


def fetch_image(file: str | Path, timeout: float = 30) -> bytes | None:
    """Return the content of an image file, remote (http, https, ftp) or local.

    Return None if it can not be read.
    """
    file = str(file)
    try:
        if is_remote(file):
            with urlopen(file, timeout=timeout) as response:
                return bytes(response.read())
        return Path(file).read_bytes()
    except FileNotFoundError:
        logger.error("%s does not exist!", file)
    except (URLError, OSError) as err:
        logger.error("Can not load %s: %s", file, err)
    return None


def open_image(data: bytes, name: str = "image") -> Image.Image | None:
    """Decode the content of an image file; return None if it is not a valid image."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except OSError as err:
        logger.error("Can not read image %s: %s", name, err)
        return None
    return image


def load_image(file: str | Path, timeout: float = 30) -> Image.Image | None:
    """Load an image remotely (http, https, ftp) or locally.

    Return None if the image can not be loaded.
    """
    data = fetch_image(file, timeout=timeout)
    if data is None:
        return None
    return open_image(data, str(file))
