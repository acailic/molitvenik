"""Image helpers of the pipeline: loading, scaling, greyscale and the colour of a word.

Every step that looks at pixels goes through these functions, so that the same page
always gives the same size, the same greyscale and the same colour decisions.
"""

import numpy as np
from PIL import Image

INK_MAX = 160  # min(R, G, B) below this is ink
RED_DELTA = 40  # R − G above this makes ink red


def load_rgb(path) -> np.ndarray:
    """Pixels of an image file as a uint8 array of shape (height, width, 3)."""
    with Image.open(path) as image:
        return np.array(image.convert("RGB"))


def resize(rgb: np.ndarray, scale: float) -> np.ndarray:
    """Scale an RGB array by `scale` with Lanczos resampling.

    The size is rounded half up: round() takes an odd half down, and half of the
    3301 rows of an Archive page has to be the 1651 that the page files have."""
    height, width = rgb.shape[:2]
    size = (int(width * scale + 0.5), int(height * scale + 0.5))
    with Image.fromarray(rgb, "RGB") as image:
        return np.array(image.resize(size, Image.Resampling.LANCZOS))


def to_greyscale(rgb: np.ndarray) -> np.ndarray:
    """Luma of an RGB image, as float 0..255.

    It is Pillow's own conversion to "L", so that these values are exactly the
    ones Tesseract is given."""
    with Image.fromarray(rgb, "RGB") as image:
        return np.asarray(image.convert("L"), dtype=np.float64)


def red_share(box: dict, rgb: np.ndarray) -> float:
    """Share of the ink inside a word box that is red; 0.0 when the box holds no ink.

    The box is trimmed by a quarter of its height at the top and at the bottom:
    the leading is tight, so a whole band always shows parts of the lines above
    and below, which are often printed in the other colour."""
    height, width = rgb.shape[:2]
    x0, x1 = max(0, box["left"]), min(width, box["left"] + box["width"])
    y0 = max(0, box["top"] + box["height"] // 4)
    y1 = min(height, box["top"] + box["height"] - box["height"] // 4)
    patch = rgb[y0:y1, x0:x1].astype(np.int16)  # signed, so that R − G can go below zero
    if patch.size == 0:
        return 0.0
    ink = patch.min(axis=2) < INK_MAX
    n_ink = int(ink.sum())
    if n_ink == 0:
        return 0.0
    red = int(((patch[..., 0] - patch[..., 1] > RED_DELTA) & ink).sum())
    return red / n_ink
