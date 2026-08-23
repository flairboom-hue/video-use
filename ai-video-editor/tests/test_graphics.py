"""Graphics generators — the guards, not the pixels.

Rendering is verified by looking at frames; what belongs in a fast suite is
the behaviour around it: what the registry offers, what it refuses, and how
input is normalised. A generator that silently draws nothing is the failure
mode worth pinning.
"""
from __future__ import annotations

import pytest

from engine.graphics import (CAPTION_SAFE_BOTTOM, GENERATORS, ICONS, Style,
                             available_icons, available_kinds, available_themes,
                             ease_in_out_cubic, ease_out_cubic, icon_row,
                             make_style, pie_chart)


class TestRegistry:
    def test_only_implemented_kinds_are_offered(self):
        # A menu entry with no generator behind it is a dead button.
        assert set(available_kinds()) == set(GENERATORS)

    def test_the_new_kinds_are_registered(self):
        assert {"pie_chart", "icon_row"} <= set(available_kinds())

    def test_every_named_icon_is_drawable(self):
        assert set(available_icons()) == set(ICONS)
        assert all(callable(fn) for fn in ICONS.values())


class TestThemes:
    def test_every_theme_builds_a_usable_style(self):
        for name in available_themes():
            st = make_style(name, width=1280, height=720)
            assert st.width == 1280 and st.text and st.accent

    def test_an_unknown_theme_raises_rather_than_falling_back(self):
        # A graphic rendered in the wrong theme is worse than one that stops.
        with pytest.raises(Exception) as exc:
            make_style("neon_wedding")
        assert "unknown theme" in str(exc.value)

    def test_overrides_win_over_the_preset(self):
        assert make_style("light_card", width=999).width == 999

    def test_light_themes_carry_a_panel_and_dark_type(self):
        # The plate, not the palette, is what makes a light design work over
        # dark footage.
        for name in ("light_card", "soft_light"):
            st = make_style(name)
            assert st.panel is not None
            assert sum(st.text) < 300, "light theme needs dark type"

    def test_the_contour_theme_has_no_panel_and_a_real_stroke(self):
        st = make_style("bold_outline")
        assert st.panel is None
        assert st.outline is not None and st.outline_width >= 4

    def test_panel_less_themes_use_no_near_white_fill(self):
        # bold_outline once used white for the secondary fill, which vanished
        # on bright footage — the exact failure the contour exists to prevent.
        # Near-white is min(channel) high; a saturated colour always has one
        # low channel, which is what keeps it separable on a bright ground.
        for name in available_themes():
            st = make_style(name)
            if st.panel is not None:
                continue                     # a plate provides the contrast
            for role, colour in (("accent", st.accent), ("accent_2", st.accent_2)):
                assert min(colour) < 200, (
                    f"{name}.{role} {colour} is near-white and needs a panel "
                    "or a darker partner to survive bright footage")


class TestEasing:
    def test_curves_are_anchored_at_both_ends(self):
        for fn in (ease_out_cubic, ease_in_out_cubic):
            assert fn(0.0) == pytest.approx(0.0)
            assert fn(1.0) == pytest.approx(1.0)

    def test_ease_out_front_loads_the_movement(self):
        # Slow landing is the whole point; linear would read as robotic.
        assert ease_out_cubic(0.5) > 0.5


class TestStyle:
    def test_caption_band_is_reserved_when_captions_exist(self):
        st = Style(height=1000, reserve_caption_band=True)
        assert st.content_height == pytest.approx(1000 * (1 - CAPTION_SAFE_BOTTOM))

    def test_without_captions_the_whole_frame_is_usable(self):
        assert Style(height=1000, reserve_caption_band=False).content_height == 1000

    def test_a_missing_font_path_falls_back_rather_than_raising(self):
        assert Style(font_path="/nope/missing.ttf").font(20) is not None


class TestPieChartGuards:
    def test_empty_values_are_refused(self, tmp_path):
        with pytest.raises(Exception):
            pie_chart(tmp_path / "x.mov", [])


class TestIconRowGuards:
    def test_an_unknown_icon_raises_instead_of_drawing_nothing(self, tmp_path):
        # A blank where an icon should be is the failure this set exists to avoid.
        with pytest.raises(Exception) as exc:
            icon_row(tmp_path / "x.mov", [("definitely_not_an_icon", "x")])
        assert "unknown icon" in str(exc.value)

    def test_empty_items_are_refused(self, tmp_path):
        with pytest.raises(Exception):
            icon_row(tmp_path / "x.mov", [])
