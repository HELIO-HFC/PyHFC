# SPDX-License-Identifier: EUPL-1.2
"""Disk cache of the HFC viewer, and its settings.

The cache holds the quicklook images (stored as downloaded, without
re-encoding) and the responses of the HQI. It is stored in the user cache
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
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

APP_NAME = "pyhfc"
#: 1 MB, as displayed to the users
MB = 1_000_000
#: Default maximum size of the cache, in MB
DEFAULT_MAX_SIZE_MB = 500
#: Default interval between two checks of the servers, and its minimum, in seconds
DEFAULT_PING_INTERVAL_S = 60
MIN_PING_INTERVAL_S = 10


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
    #: Interval between two checks of the servers (HQI, images), in seconds
    ping_interval_s: int = DEFAULT_PING_INTERVAL_S
    #: Time range dt (in seconds) of each feature: its contours are looked for in
    #: [t - dt, t + dt] around the date t of the observation (0: at the date t only)
    feature_time_ranges: dict[str, int] = field(default_factory=dict)

    @staticmethod
    def default_path() -> Path:
        return user_config_dir() / "hfcviewer.json"

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """Load the settings (default values if the file, or a setting, is missing or invalid)."""
        path = path or cls.default_path()
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise TypeError("not a JSON object")
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError, TypeError) as err:
            logger.warning("Invalid settings file %s (%s): default settings used", path, err)
            return cls()
        settings = cls()
        for name, minimum in (("cache_max_size_mb", 0), ("ping_interval_s", MIN_PING_INTERVAL_S)):
            if name not in data:
                continue
            try:
                setattr(settings, name, max(minimum, int(data[name])))
            except (ValueError, TypeError):
                logger.warning("Invalid setting %s=%r: default value used", name, data[name])
        ranges = data.get("feature_time_ranges", {})
        if isinstance(ranges, dict):
            for key, value in ranges.items():
                try:
                    settings.feature_time_ranges[str(key)] = max(0, int(value))
                except (ValueError, TypeError):
                    logger.warning("Invalid time range %s=%r: ignored", key, value)
        return settings

    def save(self, path: Path | None = None) -> None:
        path = path or self.default_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")


# ________________ Disk cache ____________________

#: Sections of the cache: quicklook images, and responses of the HQI
IMAGES = "images"
HQI = "hqi"
SECTIONS = (IMAGES, HQI)


class DiskCache:
    """Disk cache of the viewer (quicklook images, responses of the HQI), with a maximum size.

    Each section is a subdirectory of the cache. When storing a file would
    exceed the maximum size of the whole cache, it is not stored, and
    :attr:`full` becomes true: the cache then stores no more files until it
    is emptied (:meth:`clear`) or its maximum size increased.
    """

    def __init__(self, directory: Path, max_size: int) -> None:
        self.directory = Path(directory)
        self._max_size = max(0, max_size)
        self.full = False

    @classmethod
    def from_settings(cls, settings: Settings) -> DiskCache:
        return cls(user_cache_dir(), settings.cache_max_size_mb * MB)

    @property
    def max_size(self) -> int:
        """Maximum size of the cache, in bytes."""
        return self._max_size

    @max_size.setter
    def max_size(self, value: int) -> None:
        self._max_size = max(0, value)
        # new files can be stored again if the cache is no longer full
        if self.size() < self._max_size:
            self.full = False

    def path(self, key: str, section: str = IMAGES) -> Path:
        """Return the file of the cache for a key.

        The images are named by the hash of their url and its extension, the
        responses of the HQI by their key (already a hash) and ".xml".
        """
        if section == HQI:
            return self.directory / HQI / f"{key}.xml"
        suffix = Path(urlsplit(key).path).suffix.lower()
        if not suffix.isascii() or not suffix[1:].isalnum() or len(suffix) > 6:
            suffix = ""
        return self.directory / section / (hashlib.sha256(key.encode()).hexdigest() + suffix)

    def files(self, section: str | None = None) -> list[Path]:
        """Return the cached files (of a section, or of all of them)."""
        found = []
        for name in SECTIONS if section is None else (section,):
            directory = self.directory / name
            if directory.is_dir():
                found += [path for path in directory.iterdir() if path.is_file()]
        return found

    def size(self) -> int:
        """Total size of the cached files, in bytes."""
        total = 0
        for path in self.files():
            with contextlib.suppress(OSError):  # removed meanwhile
                total += path.stat().st_size
        return total

    def count(self, section: str | None = None) -> int:
        return len(self.files(section))

    def __len__(self) -> int:
        return self.count()

    def get(self, key: str, section: str = IMAGES) -> bytes | None:
        """Return the cached content of a key, or None."""
        path = self.path(key, section)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as err:
            logger.warning("Can not read the cached file %s: %s", path, err)
            return None

    def put(self, key: str, data: bytes, section: str = IMAGES, replace: bool = False) -> bool:
        """Store the content of a key; return False if it is not stored.

        The content is not stored if the cache is full, i.e. if it would
        exceed the maximum size of the cache.
        """
        if self.full:
            return False
        path = self.path(key, section)
        if path.exists() and not replace:
            return True
        if self.size() + len(data) > self._max_size:
            logger.info("The cache is full (%i bytes)", self._max_size)
            self.full = True
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # written atomically, so that a partial file is never read
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
                tmp.write(data)
            Path(tmp.name).replace(path)
        except OSError as err:
            logger.warning("Can not cache %s: %s", key, err)
            return False
        return True

    def remove(self, key: str, section: str = IMAGES) -> None:
        """Remove a key from the cache (e.g. an invalid file)."""
        self.path(key, section).unlink(missing_ok=True)

    def clear(self) -> int:
        """Remove all the cached files, and return their number."""
        number = 0
        for path in self.files():
            try:
                path.unlink()
                number += 1
            except OSError as err:
                logger.warning("Can not remove %s: %s", path, err)
        self.full = False
        return number


class HQIResponseCache:
    """Cache of the responses of the HQI, stored in a :class:`DiskCache`.

    Implements :class:`pyhfc.api.client.ResponseCache`. The expiration date of
    a response is stored on the first line of its file.
    """

    def __init__(self, cache: DiskCache) -> None:
        self.cache = cache

    def get(self, key: str) -> bytes | None:
        data = self.cache.get(key, HQI)
        if data is None:
            return None
        header, _, content = data.partition(b"\n")
        try:
            expires = float(header.removeprefix(b"expires="))
        except ValueError:
            expires = -1.0  # invalid file
        if expires and expires < time.time():
            self.cache.remove(key, HQI)
            return None
        return content

    def put(self, key: str, data: bytes, max_age: float | None = None) -> bool:
        expires = time.time() + max_age if max_age is not None else 0.0
        header = f"expires={expires:.0f}\n".encode()
        return self.cache.put(key, header + data, HQI, replace=True)
