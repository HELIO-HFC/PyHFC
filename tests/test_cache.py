# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from pyhfc.hfcviewer import cache
from pyhfc.hfcviewer.cache import HQI, IMAGES, MB, DiskCache, HQIResponseCache, Settings

URL = "ftp://example.org/qclk/2012/image.png"


@pytest.mark.parametrize(
    ("platform", "cache_dir", "config_dir"),
    [
        ("darwin", "Library/Caches/pyhfc", "Library/Application Support/pyhfc"),
        ("linux", ".cache/pyhfc", ".config/pyhfc"),
    ],
)
def test_user_dirs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    platform: str,
    cache_dir: str,
    config_dir: str,
) -> None:
    for name in ("PYHFC_CACHE_DIR", "PYHFC_CONFIG_DIR", "XDG_CACHE_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("pyhfc.hfcviewer.cache.sys.platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert cache.user_cache_dir() == tmp_path / cache_dir
    assert cache.user_config_dir() == tmp_path / config_dir


def test_user_dirs_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PYHFC_CACHE_DIR", str(tmp_path / "c"))
    monkeypatch.setenv("PYHFC_CONFIG_DIR", str(tmp_path / "s"))
    assert cache.user_cache_dir() == tmp_path / "c"
    assert cache.user_config_dir() == tmp_path / "s"


def test_settings(tmp_path: Path) -> None:
    path = tmp_path / "settings" / "hfcviewer.json"
    assert Settings.load(path) == Settings(cache_max_size_mb=500)  # default
    Settings(cache_max_size_mb=250).save(path)
    assert json.loads(path.read_text()) == {"cache_max_size_mb": 250, "ping_interval_s": 60}
    assert Settings.load(path).cache_max_size_mb == 250


@pytest.mark.parametrize("content", ["not json", "{}", '{"cache_max_size_mb": "x"}'])
def test_settings_invalid(tmp_path: Path, content: str) -> None:
    path = tmp_path / "hfcviewer.json"
    path.write_text(content)
    assert Settings.load(path) == Settings()


def test_settings_default_path_and_cache() -> None:
    # isolated in temporary directories by the conftest
    assert Settings.default_path() == cache.user_config_dir() / "hfcviewer.json"
    disk_cache = DiskCache.from_settings(Settings(cache_max_size_mb=5))
    assert disk_cache.directory == cache.user_cache_dir()
    assert disk_cache.max_size == 5 * MB
    # the images are in the "images" subdirectory, as before
    assert disk_cache.path(URL).parent == cache.user_cache_dir() / "images"


def test_cache_put_get(tmp_path: Path) -> None:
    disk_cache = DiskCache(tmp_path, 1000)
    assert disk_cache.get(URL) is None
    assert len(disk_cache) == 0
    assert disk_cache.size() == 0
    assert disk_cache.put(URL, b"x" * 300)
    assert disk_cache.get(URL) == b"x" * 300
    assert disk_cache.put(URL, b"x" * 300)  # already cached
    assert len(disk_cache) == 1
    assert disk_cache.size() == 300
    # stored with the extension of the url, without temporary files left
    assert [path.suffix for path in disk_cache.files()] == [".png"]
    assert disk_cache.files(IMAGES) == disk_cache.files()
    assert disk_cache.count(HQI) == 0
    disk_cache.remove(URL)
    assert disk_cache.get(URL) is None


@pytest.mark.parametrize(
    ("url", "suffix"),
    [
        ("ftp://h/a/hmi.Ic_45s.2017.10.10_02:00:00_TAI.continuum.jpg", ".jpg"),
        ("http://h/image?id=3", ""),
        ("http://h/image.verylongext", ""),
    ],
)
def test_cache_path(tmp_path: Path, url: str, suffix: str) -> None:
    path = DiskCache(tmp_path, 10).path(url)
    assert path.parent == tmp_path / "images"
    assert path.suffix == suffix
    assert len(path.stem) == 64


def test_cache_full(tmp_path: Path) -> None:
    disk_cache = DiskCache(tmp_path, 1000)
    assert disk_cache.put("ftp://h/1.png", b"x" * 600)
    assert not disk_cache.full
    # would exceed the maximum size: not stored, and the cache is full
    assert not disk_cache.put("ftp://h/2.png", b"x" * 600)
    assert disk_cache.full
    # no new image is stored, even a small one
    assert not disk_cache.put("ftp://h/3.png", b"x")
    assert len(disk_cache) == 1
    # increasing the maximum size allows to store images again
    disk_cache.max_size = 2000
    assert not disk_cache.full
    assert disk_cache.put("ftp://h/2.png", b"x" * 600)


def test_cache_clear(tmp_path: Path) -> None:
    disk_cache = DiskCache(tmp_path, 100)
    disk_cache.put("ftp://h/1.png", b"x" * 60)
    disk_cache.put("ftp://h/2.png", b"x" * 60)
    assert disk_cache.full
    assert disk_cache.clear() == 1
    assert not disk_cache.full
    assert len(disk_cache) == 0
    assert disk_cache.put("ftp://h/2.png", b"x" * 60)


def test_cache_zero_size(tmp_path: Path) -> None:
    disk_cache = DiskCache(tmp_path, 0)
    assert not disk_cache.put(URL, b"x")
    assert disk_cache.full
    assert disk_cache.files() == []


def test_cache_sections_share_the_maximum_size(tmp_path: Path) -> None:
    disk_cache = DiskCache(tmp_path, 1000)
    assert disk_cache.put("ftp://h/1.png", b"x" * 500)
    assert disk_cache.put("abc", b"y" * 400, HQI)
    assert disk_cache.path("abc", HQI) == tmp_path / "hqi" / "abc.xml"
    assert disk_cache.count(IMAGES) == 1
    assert disk_cache.count(HQI) == 1
    assert len(disk_cache) == 2
    assert disk_cache.size() == 900
    # the whole cache is full, for all the sections
    assert not disk_cache.put("ftp://h/2.png", b"x" * 200)
    assert disk_cache.full
    assert not disk_cache.put("def", b"y", HQI)
    assert disk_cache.clear() == 2


def test_hqi_response_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    disk_cache = DiskCache(tmp_path, 10_000)
    responses = HQIResponseCache(disk_cache)
    assert responses.get("key") is None
    assert responses.put("key", b"<VOTABLE/>")  # no expiration
    assert responses.put("recent", b"<VOTABLE>recent</VOTABLE>", max_age=60)
    assert responses.get("key") == b"<VOTABLE/>"
    assert responses.get("recent") == b"<VOTABLE>recent</VOTABLE>"
    assert disk_cache.count(HQI) == 2

    # one hour later: the recent response has expired, and is removed
    now = time.time()
    monkeypatch.setattr("pyhfc.hfcviewer.cache.time.time", lambda: now + 3600)
    assert responses.get("recent") is None
    assert responses.get("key") == b"<VOTABLE/>"
    assert disk_cache.count(HQI) == 1
    # an expired response can be cached again
    assert responses.put("recent", b"<VOTABLE>new</VOTABLE>", max_age=60)
    assert responses.get("recent") == b"<VOTABLE>new</VOTABLE>"


def test_hqi_response_cache_invalid_file(tmp_path: Path) -> None:
    disk_cache = DiskCache(tmp_path, 10_000)
    disk_cache.put("bad", b"no header", HQI)
    responses = HQIResponseCache(disk_cache)
    assert responses.get("bad") is None
    assert disk_cache.count(HQI) == 0


def test_settings_partial_and_invalid_values(tmp_path: Path) -> None:
    path = tmp_path / "hfcviewer.json"
    # settings file of a previous version (no ping interval)
    path.write_text('{"cache_max_size_mb": 300}')
    assert Settings.load(path) == Settings(cache_max_size_mb=300, ping_interval_s=60)
    # an invalid value does not discard the other settings
    path.write_text('{"cache_max_size_mb": 300, "ping_interval_s": "often"}')
    assert Settings.load(path) == Settings(cache_max_size_mb=300, ping_interval_s=60)
    # minimum interval
    path.write_text('{"ping_interval_s": 1}')
    assert Settings.load(path).ping_interval_s == cache.MIN_PING_INTERVAL_S
    path.write_text("[1, 2]")
    assert Settings.load(path) == Settings()
