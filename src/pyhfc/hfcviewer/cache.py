# SPDX-License-Identifier: EUPL-1.2
"""Disk cache of the quicklook images loaded by the HFC viewer, and its settings.

The images are stored as downloaded (no re-encoding), in the user cache
directory of the platform (``PYHFC_CACHE_DIR`` to use another directory). The
maximum size of the cache is a setting of the viewer, saved in the user
configuration directory (``PYHFC_CONFIG_DIR`` to use another directory).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

APP_NAME = "pyhfc"
#: 1 MB, as displayed to the users
MB = 1_000_000
#: Default maximum size of the cache, in MB
DEFAULT_MAX_SIZE_MB = 100


def user_cache_dir() -> Path:
    """Return the cache directory of pyhfc on this platform."""
    if env := os.environ.get("PYHFC_CACHE_DIR"):
        return Path(env)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_NAME
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME / "Cache"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / APP_NAME


def user_config_dir() -> Path:
    """Return the configuration directory of pyhfc on this platform."""
    if env := os.environ.get("PYHFC_CONFIG_DIR"):
        return Path(env)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME


# ________________ Settings ______________________


@dataclass
class Settings:
    """Settings of the HFC viewer, saved in a JSON file."""

    cache_max_size_mb: int = DEFAULT_MAX_SIZE_MB

    @staticmethod
    def default_path() -> Path:
        return user_config_dir() / "hfcviewer.json"

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """Load the settings (default values if the file is missing or invalid)."""
        path = path or cls.default_path()
        try:
            data = json.loads(path.read_text())
            return cls(cache_max_size_mb=max(0, int(data["cache_max_size_mb"])))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError, TypeError, KeyError) as err:
            logger.warning("Invalid settings file %s (%s): default settings used", path, err)
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or self.default_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")


# ________________ Image cache ___________________


class ImageCache:
    """Disk cache of images, with a maximum size.

    When storing an image would exceed the maximum size, the image is not
    stored, and :attr:`full` becomes true: the cache then stores no more
    images until it is emptied (:meth:`clear`) or its maximum size increased.
    """

    def __init__(self, directory: Path, max_size: int) -> None:
        self.directory = Path(directory)
        self._max_size = max(0, max_size)
        self.full = False

    @classmethod
    def from_settings(cls, settings: Settings) -> ImageCache:
        return cls(user_cache_dir() / "images", settings.cache_max_size_mb * MB)

    @property
    def max_size(self) -> int:
        """Maximum size of the cache, in bytes."""
        return self._max_size

    @max_size.setter
    def max_size(self, value: int) -> None:
        self._max_size = max(0, value)
        # new images can be stored again if the cache is no longer full
        if self.size() < self._max_size:
            self.full = False

    def path(self, url: str) -> Path:
        """Return the file of the cache for an url (hash of the url + its extension)."""
        suffix = Path(urlsplit(url).path).suffix.lower()
        if not suffix.isascii() or not suffix[1:].isalnum() or len(suffix) > 6:
            suffix = ""
        return self.directory / (hashlib.sha256(url.encode()).hexdigest() + suffix)

    def files(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return [path for path in self.directory.iterdir() if path.is_file()]

    def size(self) -> int:
        """Total size of the cached images, in bytes."""
        total = 0
        for path in self.files():
            with contextlib.suppress(OSError):  # removed meanwhile
                total += path.stat().st_size
        return total

    def __len__(self) -> int:
        return len(self.files())

    def get(self, url: str) -> bytes | None:
        """Return the cached content of an url, or None."""
        path = self.path(url)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as err:
            logger.warning("Can not read the cached image %s: %s", path, err)
            return None

    def put(self, url: str, data: bytes) -> bool:
        """Store the content of an url; return False if it is not stored.

        The content is not stored if the cache is full, i.e. if it would
        exceed the maximum size of the cache.
        """
        if self.full:
            return False
        path = self.path(url)
        if path.exists():
            return True
        if self.size() + len(data) > self._max_size:
            logger.info("The image cache is full (%i bytes)", self._max_size)
            self.full = True
            return False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # written atomically, so that a partial file is never read
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as tmp:
                tmp.write(data)
            Path(tmp.name).replace(path)
        except OSError as err:
            logger.warning("Can not cache the image of %s: %s", url, err)
            return False
        return True

    def remove(self, url: str) -> None:
        """Remove an url from the cache (e.g. an invalid image)."""
        self.path(url).unlink(missing_ok=True)

    def clear(self) -> int:
        """Remove all the cached images, and return their number."""
        number = 0
        for path in self.files():
            try:
                path.unlink()
                number += 1
            except OSError as err:
                logger.warning("Can not remove %s: %s", path, err)
        self.full = False
        return number
