"""The storyboard's two load-bearing details.

Everything else in that script is drawing, and drawing is checked by looking.
These two are not: one silently corrupts every later render in the process,
the other silently ran text into the neighbouring column.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "beispiele" / "pogo-gnom"))

import storyboard  # noqa: E402

from engine import graphics as gfx  # noqa: E402


class TestGeneratorInterception:
    """grafik_frame swaps out a module global to capture one frame."""

    def test_the_real_renderer_is_put_back(self):
        before = gfx._render
        storyboard.grafik_frame(gfx.text_animation, "hallo",
                                gfx.make_style("light_card", width=320, height=180))
        assert gfx._render is before

    def test_it_is_put_back_even_when_the_generator_raises(self):
        # Without the finally, one bad call leaves _render stubbed and every
        # later render in the same process writes nothing, quietly.
        before = gfx._render
        with pytest.raises(Exception):
            storyboard.grafik_frame(gfx.text_animation)      # missing argument
        assert gfx._render is before

    def test_the_captured_frame_is_the_real_graphic(self):
        st = gfx.make_style("light_card", width=320, height=180)
        layer = storyboard.grafik_frame(gfx.text_animation, "hallo", st)
        assert layer.size == (storyboard.W, storyboard.H)
        assert layer.getbbox() is not None, "nothing was drawn"


class TestLabelFitting:
    @staticmethod
    def _draw():
        from PIL import Image, ImageDraw
        return ImageDraw.Draw(Image.new("RGB", (10, 10)))

    def test_short_text_is_left_alone(self):
        st = gfx.make_style("light_card")
        font = st.font(24)
        assert storyboard._fit(self._draw(), "kurz", font, 600) == "kurz"

    def test_long_text_is_cut_to_the_measured_width(self):
        # Cutting by character count was the bug: the same 64 characters are
        # wider than the column in one label and half its width in another,
        # and the overhang ran into the next column.
        d, font = self._draw(), gfx.make_style("light_card").font(24)
        out = storyboard._fit(d, "Karte verdeckt das Gesicht — auf Spielbild schneiden",
                              font, 200)
        assert out.endswith("…")
        assert gfx._text_size(d, out, font)[0] <= 200


class TestBlocks:
    def test_every_block_has_all_five_fields(self):
        st = gfx.make_style("light_card")
        for block in storyboard.panels(st):
            zeit, name, notiz, fn, konflikt = block
            assert zeit and name and notiz and callable(fn)
            assert isinstance(konflikt, str)

    def test_the_face_and_card_collisions_are_marked(self):
        # A card is a full-width plate over the middle of the frame, which is
        # where a head is. The two blocks where the plan asks for both must
        # say so rather than look fine in the storyboard and fail in the edit.
        st = gfx.make_style("light_card")
        marked = {z for z, _, _, _, k in storyboard.panels(st) if k}
        assert marked == {"0:08", "10:20"}
