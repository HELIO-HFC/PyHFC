# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyhfc.hfcviewer import cache
from pyhfc.hfcviewer.cache import MB, ImageCache, Settings

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
    assert Settings.load(path) == Settings(cache_max_size_mb=100)  # default
    Settings(cache_max_size_mb=250).save(path)
    assert json.loads(path.read_text()) == {"cache_max_size_mb": 250}
    assert Settings.load(path).cache_max_size_mb == 250


@pytest.mark.parametrize("content", ["not json", "{}", '{"cache_max_size_mb": "x"}'])
def test_settings_invalid(tmp_path: Path, content: str) -> None:
    path = tmp_path / "hfcviewer.json"
    path.write_text(content)
    assert Settings.load(path) == Settings()


def test_settings_default_path_and_cache() -> None:
    # isolated in temporary directories by the conftest
    assert Settings.default_path() == cache.user_config_dir() / "hfcviewer.json"
    image_cache = ImageCache.from_settings(Settings(cache_max_size_mb=5))
    assert image_cache.directory == cache.user_cache_dir() / "images"
    assert image_cache.max_size == 5 * MB


def test_cache_put_get(tmp_path: Path) -> None:
    image_cache = ImageCache(tmp_path / "images", 1000)
    assert image_cache.get(URL) is None
    assert len(image_cache) == 0
    assert image_cache.size() == 0
    assert image_cache.put(URL, b"x" * 300)
    assert image_cache.get(URL) == b"x" * 300
    assert image_cache.put(URL, b"x" * 300)  # already cached
    assert len(image_cache) == 1
    assert image_cache.size() == 300
    # stored with the extension of the url, without temporary files left
    assert [path.suffix for path in image_cache.files()] == [".png"]
    image_cache.remove(URL)
    assert image_cache.get(URL) is None


@pytest.mark.parametrize(
    ("url", "suffix"),
    [
        ("ftp://h/a/hmi.Ic_45s.2017.10.10_02:00:00_TAI.continuum.jpg", ".jpg"),
        ("http://h/image?id=3", ""),
        ("http://h/image.verylongext", ""),
    ],
)
def test_cache_path(tmp_path: Path, url: str, suffix: str) -> None:
    path = ImageCache(tmp_path, 10).path(url)
    assert path.parent == tmp_path
    assert path.suffix == suffix
    assert len(path.stem) == 64


def test_cache_full(tmp_path: Path) -> None:
    image_cache = ImageCache(tmp_path, 1000)
    assert image_cache.put("ftp://h/1.png", b"x" * 600)
    assert not image_cache.full
    # would exceed the maximum size: not stored, and the cache is full
    assert not image_cache.put("ftp://h/2.png", b"x" * 600)
    assert image_cache.full
    # no new image is stored, even a small one
    assert not image_cache.put("ftp://h/3.png", b"x")
    assert len(image_cache) == 1
    # increasing the maximum size allows to store images again
    image_cache.max_size = 2000
    assert not image_cache.full
    assert image_cache.put("ftp://h/2.png", b"x" * 600)


def test_cache_clear(tmp_path: Path) -> None:
    image_cache = ImageCache(tmp_path, 100)
    image_cache.put("ftp://h/1.png", b"x" * 60)
    image_cache.put("ftp://h/2.png", b"x" * 60)
    assert image_cache.full
    assert image_cache.clear() == 1
    assert not image_cache.full
    assert len(image_cache) == 0
    assert image_cache.put("ftp://h/2.png", b"x" * 60)


def test_cache_zero_size(tmp_path: Path) -> None:
    image_cache = ImageCache(tmp_path, 0)
    assert not image_cache.put(URL, b"x")
    assert image_cache.full
    assert image_cache.files() == []
