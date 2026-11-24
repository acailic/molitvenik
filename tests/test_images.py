"""images.py: loading, scaling, greyscale and the colour of a word box."""

import numpy as np
import pytest
from molitvenik_tools import images
from PIL import Image

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (190, 40, 40)  # the red ink of the scan


def blank(width=40, height=20):
    """A white image as a uint8 array of shape (height, width, 3)."""
    return np.full((height, width, 3), WHITE, dtype=np.uint8)


def painted(rgb, left, top, width, height, colour):
    """`rgb` with a rectangle of one colour painted into it."""
    rgb[top : top + height, left : left + width] = colour
    return rgb


def box(left=0, top=0, width=20, height=20):
    """A word box as the OCR page files hold it."""
    return {"left": left, "top": top, "width": width, "height": height}


def test_black_word_on_white_has_no_red_ink():
    rgb = painted(blank(), 10, 0, 20, 20, BLACK)
    assert images.red_share(box(10), rgb) == 0.0


def test_red_word_is_all_red_ink():
    rgb = painted(blank(), 10, 0, 20, 20, RED)
    assert images.red_share(box(10), rgb) == 1.0


def test_word_half_red_half_black_is_about_half_red():
    rgb = painted(painted(blank(), 0, 0, 10, 20, RED), 10, 0, 10, 20, BLACK)
    assert images.red_share(box(), rgb) == pytest.approx(0.5, abs=0.01)


def test_box_without_ink_has_no_red():
    assert images.red_share(box(), blank()) == 0.0


def test_box_of_no_size_or_outside_the_image_has_no_red():
    assert images.red_share(box(0, 0, 0, 20), painted(blank(), 0, 0, 40, 20, RED)) == 0.0
    assert images.red_share(box(100, 100, 10, 10), painted(blank(), 0, 0, 40, 20, RED)) == 0.0


def test_box_is_trimmed_by_a_quarter_of_its_height_at_top_and_bottom():
    # Black bands in the top and the bottom quarter of the box stand for the lines
    # above and below, which the tight leading lets show in any band: they must not count.
    rgb = painted(blank(40, 40), 10, 10, 20, 20, RED)
    rgb = painted(rgb, 10, 10, 20, 5, BLACK)
    rgb = painted(rgb, 10, 25, 20, 5, BLACK)
    assert images.red_share(box(10, 10, 20, 20), rgb) == 1.0


def test_box_sticking_out_of_the_image_is_cut_to_it():
    rgb = painted(blank(40, 20), 30, 0, 10, 20, RED)
    assert images.red_share(box(30, 0, 30, 40), rgb) == 1.0


def test_greyscale_of_pure_red_is_dark():
    red = np.array([[[255, 0, 0]]], dtype=np.uint8)
    assert images.to_greyscale(red)[0, 0] < 110


def test_greyscale_is_luma_as_float_of_the_same_size():
    rgb = np.array([[[255, 255, 255], [0, 0, 0], [255, 0, 0]]], dtype=np.uint8)
    grey = images.to_greyscale(rgb)
    assert grey.shape == (1, 3)
    assert grey.dtype.kind == "f"
    assert grey.tolist() == [[255.0, 0.0, 76.0]]


def test_load_rgb_reads_a_file_as_pixels(tmp_path):
    path = tmp_path / "p.png"
    Image.new("RGB", (3, 2), RED).save(path)
    rgb = images.load_rgb(path)
    assert rgb.shape == (2, 3, 3)
    assert rgb.dtype == np.uint8
    assert (rgb == RED).all()


def test_load_rgb_makes_three_channels_whatever_the_file_holds(tmp_path):
    path = tmp_path / "grey.png"
    Image.new("L", (3, 2), 7).save(path)
    rgb = images.load_rgb(path)
    assert rgb.shape == (2, 3, 3)
    assert (rgb == 7).all()


@pytest.mark.parametrize(
    ("shape", "scale", "size"),
    [
        ((21, 33), 0.5, (11, 17)),  # an odd number of pixels rounds half up
        ((3301, 2019), 0.5, (1651, 1010)),  # half of an Archive page: the size of the page files
        ((3301, 2019), 0.4, (1320, 808)),  # the reading at 40 %
        ((1754, 1240), 2.0, (3508, 2480)),  # a page of the 150 DPI PDF, upscaled
        ((10, 25), 1.0, (10, 25)),
    ],
)
def test_resize_scales_both_sides_and_rounds_half_up(shape, scale, size):
    rgb = np.zeros((*shape, 3), dtype=np.uint8)
    out = images.resize(rgb, scale)
    assert out.shape == (*size, 3)
    assert out.dtype == np.uint8


def test_resize_resamples_instead_of_cropping():
    rgb = painted(blank(4, 2), 2, 0, 2, 2, BLACK)  # the left half white, the right half black
    out = images.resize(rgb, 0.25)  # one pixel, about mid-grey
    assert out.shape == (1, 1, 3)
    assert 96 < int(out[0, 0, 0]) < 160
