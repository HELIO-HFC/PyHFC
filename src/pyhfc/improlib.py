# SPDX-License-Identifier: EUPL-1.2
"""Image processing routines used by the HFC viewer.

Author: Xavier Bonnin (LESIA)
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy import ndimage

logger = logging.getLogger(__name__)

# Chain code directions: ARDIR[i] is the [X, Y] step for the code CCDIR[i]
ARDIR = np.array([[-1, 0], [-1, 1], [0, 1], [1, 1], [1, 0], [1, -1], [0, -1], [-1, -1]])
CCDIR = np.array([0, 7, 6, 5, 4, 3, 2, 1])
STEP_BY_CODE = {str(code): (int(dx), int(dy)) for code, (dx, dy) in zip(CCDIR, ARDIR, strict=True)}


def poly_area(x: Sequence[float], y: Sequence[float]) -> float:
    """Compute the area of an irregular, closed, convex polygon.

    The x and y vectors are the vertices; the polygon is closed if needed.
    """
    xs = list(x)
    ys = list(y)
    # Must be a closed area
    if xs[-1] != xs[0] or ys[-1] != ys[0]:
        xs.append(xs[0])
        ys.append(ys[0])

    area = 0.0
    for i in range(len(xs) - 1):
        area += (xs[i] * ys[i + 1] - xs[i + 1] * ys[i]) * 0.5
    return abs(area)


def image2chain(
    image: NDArray[Any],
    pixel_value: Any,
    fill: bool = False,
    remove_isolated_pixels: bool = False,
) -> tuple[str, list[list[int]]]:
    """Compute the chain code of a feature's contour on an image.

    Inputs:
      image       - 2d numpy array
      pixel_value - pixel value of the feature on the image.
    Outputs:
      chaincode, locations - chain code of the feature's contour,
                             and locations [X, Y] of the contour's pixels
    """
    ardir = ARDIR.copy()
    ccdir = CCDIR.copy()

    if image.ndim != 2:
        logger.error("Input array must have 2 dimensions!")
        return "", []

    n = image.shape[0] * image.shape[1]
    mask: NDArray[np.bool_] = image == pixel_value

    if remove_isolated_pixels:
        mask = closerec(mask)
    if fill:
        mask = fill_holes(mask)

    indices = np.where(mask)
    if len(indices[0]) == 0:
        logger.error("No pixel with value %s in the image!", pixel_value)
        return "", []

    # Find location of the starting pixel [X, Y]
    # It must be the leftmost-uppermost pixel belonging to the feature
    cc_x_pix = int(min(indices[0]))
    cc_y_pix = int(max(indices[1][indices[0] == cc_x_pix]))

    chaincode = ""
    locations: list[list[int]] = []
    xpix, ypix = cc_x_pix, cc_y_pix
    for _ in range(n + 1):
        for i, direction in enumerate(ardir):
            x = xpix + int(direction[0])
            y = ypix + int(direction[1])
            current_ccdir = int(ccdir[i])
            if mask[x, y]:
                break
        chaincode += str(current_ccdir)
        locations.append([xpix, ypix])
        # if return to starting pixel, then stop
        if [x, y] == [cc_x_pix, cc_y_pix]:
            locations.append([x, y])
            return chaincode, locations
        # assign new pixel position
        xpix, ypix = x, y
        # rotate direction vector
        ishift = int(np.where(ccdir == (current_ccdir + 4) % 8)[0][0])
        ardir = np.roll(ardir, 7 - ishift, axis=0)
        ccdir = np.roll(ccdir, 7 - ishift)

    logger.error("Can not compute chain code!")
    return "", []


def chain2image(chaincode: str, start_pix: Sequence[int]) -> tuple[list[int], list[int]]:
    """Compute the pixel contour from a chain code and its starting pixel [X, Y].

    Raise ``ValueError`` if the inputs are not valid.
    """
    if not isinstance(chaincode, str):
        raise ValueError("First input argument must be a string!")
    if len(start_pix) != 2:
        raise ValueError("Second input argument must be a 2-elements vector!")

    xs = [int(start_pix[0])]
    ys = [int(start_pix[1])]
    for c in chaincode:
        if c not in STEP_BY_CODE:
            raise ValueError(f"Wrong chain code format: {c!r}!")
        dx, dy = STEP_BY_CODE[c]
        xs.append(xs[-1] + dx)
        ys.append(ys[-1] + dy)
    return xs, ys


def _as_binary(image: NDArray[Any]) -> NDArray[np.bool_]:
    if image.dtype == np.bool_:
        return image.copy()
    return np.asarray(image > 0)


def closerec(
    image: NDArray[Any],
    open_structure: NDArray[np.bool_] | None = None,
    close_structure: NDArray[np.bool_] | None = None,
) -> NDArray[np.bool_]:
    """Apply a closing reconstruction operator on the input binary image."""
    binary_image = _as_binary(image)

    # Multiple erosion operations
    current_image0 = binary_image
    current_image1 = binary_image.copy()
    while current_image1.any():
        current_image0 = current_image1
        current_image1 = ndimage.binary_erosion(current_image0, structure=open_structure)

    # Multiple dilatation operations
    return np.asarray(
        ndimage.binary_propagation(current_image0, structure=close_structure, mask=binary_image)
    )


def fill_holes(
    image: NDArray[Any], structure: NDArray[np.bool_] | None = None
) -> NDArray[np.bool_]:
    """Fill the holes of the input binary image."""
    return np.asarray(ndimage.binary_fill_holes(_as_binary(image), structure=structure))


def auto_contrast(image: ArrayLike, low: float = 0.02, high: float = 0.99) -> NDArray[np.float64]:
    """Adjust the contrast of an image using the histogram of its pixel values.

    Pixel values are clipped between the ``low`` and ``high`` quantiles.
    Return a new float array, the input image is not modified.
    """
    data = np.array(image, dtype=np.float64)
    if data.size == 0:
        return data
    lev_min = np.min(data) if low <= 0.0 else np.quantile(data, low)
    lev_max = np.max(data) if high >= 1.0 else np.quantile(data, high)
    return np.clip(data, lev_min, lev_max)
