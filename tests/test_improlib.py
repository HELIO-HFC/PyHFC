# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

import numpy as np
import pytest

from pyhfc.improlib import (
    auto_contrast,
    chain2image,
    closerec,
    fill_holes,
    image2chain,
    poly_area,
)


def test_poly_area_square() -> None:
    assert poly_area([0, 2, 2, 0], [0, 0, 2, 2]) == pytest.approx(4.0)


def test_poly_area_already_closed_does_not_modify_input() -> None:
    x = [0.0, 1.0, 0.0, 0.0]
    y = [0.0, 0.0, 1.0, 0.0]
    assert poly_area(x, y) == pytest.approx(0.5)
    assert x == [0.0, 1.0, 0.0, 0.0]


def test_chain2image_steps() -> None:
    xs, ys = chain2image("0246", [10, 20])
    assert xs == [10, 9, 9, 10, 10]
    assert ys == [20, 20, 19, 19, 20]


@pytest.mark.parametrize(
    ("chaincode", "start"),
    [("018", [0, 0]), ("01a", [0, 0]), ("01", [0])],
)
def test_chain2image_invalid(chaincode: str, start: list[int]) -> None:
    with pytest.raises(ValueError):
        chain2image(chaincode, start)


def test_image2chain_roundtrip() -> None:
    image = np.zeros((10, 10), dtype=int)
    image[3:7, 2:6] = 5
    chaincode, locations = image2chain(image, 5)
    assert chaincode
    assert locations[0] == locations[-1]
    xs, ys = chain2image(chaincode, locations[0])
    assert [list(p) for p in zip(xs, ys, strict=True)] == locations
    # every contour pixel belongs to the feature
    assert all(image[x, y] == 5 for x, y in locations)


def test_image2chain_without_feature() -> None:
    assert image2chain(np.zeros((5, 5)), 1) == ("", [])
    assert image2chain(np.zeros(5), 1) == ("", [])


def test_fill_holes() -> None:
    image = np.zeros((7, 7), dtype=int)
    image[1:6, 1:6] = 1
    image[3, 3] = 0
    filled = fill_holes(image)
    assert filled.dtype == np.bool_
    assert filled[3, 3]
    assert filled.sum() == 25


def test_closerec_removes_small_objects() -> None:
    image = np.zeros((20, 20), dtype=bool)
    image[2:12, 2:12] = True  # large object
    image[16, 16] = True  # isolated pixel
    result = closerec(image)
    assert result[5, 5]
    assert not result[16, 16]


def test_closerec_empty_image() -> None:
    assert not closerec(np.zeros((5, 5))).any()


def test_auto_contrast_clips_and_preserves_input() -> None:
    image = np.arange(101, dtype=np.uint8).reshape(1, 101)
    image.flags.writeable = False  # e.g. np.asarray(PIL.Image)
    result = auto_contrast(image, low=0.1, high=0.9)
    assert result.dtype == np.float64
    assert result.min() == pytest.approx(10.0)
    assert result.max() == pytest.approx(90.0)
    assert image.max() == 100


def test_auto_contrast_full_range_is_identity() -> None:
    image = np.array([[0, 5], [10, 255]])
    np.testing.assert_array_equal(auto_contrast(image, low=0.0, high=1.0), image)
