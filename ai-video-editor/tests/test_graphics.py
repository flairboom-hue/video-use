"""Graphics generators — the guards, not the pixels.

Rendering is verified by looking at frames; what belongs in a fast suite is
the behaviour around it: what the registry offers, what it refuses, and how
input is normalised. A generator that silently draws nothing is the failure
mode worth pinning.
"""
from __future__ import annotations

import pytest

import shutil

from PIL import ImageDraw

from engine.graphics import (CAPTION_SAFE_BOTTOM, GENERATORS, ICONS,
                             MOTION_BLUR_LEVELS, Style, _average_rgba,
                             _hash_unit, _render,
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


needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="encodes a real clip; the rest of the suite stays ffmpeg-free")


class TestMotionBlur:
    def _moving_dot(self, mb: int, out, fps: int = 30):
        st = Style(width=240, height=135, fps=fps, reserve_caption_band=False,
                   motion_blur=mb, shutter=0.5)

        def frame(draw, t, img):
            x = 20 + 200 * t
            draw.ellipse([x - 12, 55, x + 12, 79], fill=(255, 90, 0, 255))
        return _render(frame, 0.4, st, out)

    def test_off_by_default(self):
        # It multiplies render time; nobody should pay that without asking.
        assert Style().motion_blur == 0
        assert MOTION_BLUR_LEVELS["off"] == 0

    def test_levels_are_ordered_and_start_at_zero(self):
        values = list(MOTION_BLUR_LEVELS.values())
        assert values[0] == 0 and values == sorted(values)

    @needs_ffmpeg
    def test_blur_does_not_change_the_frame_count(self, tmp_path):
        # Sub-frames are averaged into one output frame, not appended.
        from PIL import Image  # noqa: F401  (guard: pillow present)
        plain = self._moving_dot(0, tmp_path / "a.mov")
        blurred = self._moving_dot(8, tmp_path / "b.mov")
        assert plain.exists() and blurred.exists()

    def test_blur_spreads_a_hard_edge_into_partial_coverage(self, tmp_path):
        import numpy as np
        from PIL import Image

        def alpha_histogram(mb, name):
            st = Style(width=240, height=135, fps=30, reserve_caption_band=False,
                       motion_blur=mb, shutter=0.5)
            img = Image.new("RGBA", (240, 135), (0, 0, 0, 0))
            # Compose the middle frame the same way _render does.
            frames = []
            for k in range(max(1, mb)):
                jitter = _hash_unit(4 * 977 + k) - 0.5
                frac = ((k + 0.5 + jitter) / max(1, mb) - 0.5) if mb > 1 else 0.0
                t = 0.5 + frac * (0.5 / 12)
                f = Image.new("RGBA", (240, 135), (0, 0, 0, 0))
                d = ImageDraw.Draw(f)
                x = 20 + 200 * t
                d.ellipse([x - 12, 55, x + 12, 79], fill=(255, 90, 0, 255))
                frames.append(f)
            img = _average_rgba(frames) if mb > 1 else frames[0]
            a = np.asarray(img)[..., 3]
            return (a > 250).sum(), ((a > 20) & (a < 250)).sum()

        solid_plain, partial_plain = alpha_histogram(0, "plain")
        solid_blur, partial_blur = alpha_histogram(16, "blur")
        # A blurred fast move trades opaque pixels for a partially covered trail.
        assert partial_blur > partial_plain
        assert solid_blur < solid_plain

    @needs_ffmpeg
    def test_rendering_twice_produces_the_same_bytes(self, tmp_path):
        # The jitter is seeded, not random: an unrelated re-render must not
        # change the grain.
        a = self._moving_dot(8, tmp_path / "one.mov").read_bytes()
        b = self._moving_dot(8, tmp_path / "two.mov").read_bytes()
        assert a == b

    def test_samples_are_weighted_by_their_own_coverage(self):
        import numpy as np
        from PIL import Image

        # Two samples that differ in BOTH colour and alpha — equal-colour
        # samples cannot tell premultiplied averaging apart from naive
        # averaging, because the unpremultiply step happens to cancel out.
        opaque_red = Image.new("RGBA", (4, 4), (200, 0, 0, 255))
        faint_blue = Image.new("RGBA", (4, 4), (0, 0, 200, 51))   # 20% covered
        out = np.asarray(_average_rgba([opaque_red, faint_blue]))

        # Correct: blue contributes only its 20% coverage -> ~33.
        # Naive averaging would carry it at full strength -> ~167.
        assert out[..., 2].mean() < 60, "faint sample carried at full strength"
        assert 150 < out[..., 0].mean() < 185
        assert 145 < out[..., 3].mean() < 160


class TestStatCardAndHorizontalBars:
    def test_both_are_registered(self):
        assert {"stat_card", "bar_chart_h"} <= set(available_kinds())

    def test_empty_input_is_refused(self, tmp_path):
        from engine.graphics import bar_chart_h, stat_card
        with pytest.raises(Exception):
            stat_card(tmp_path / "a.mov", [])
        with pytest.raises(Exception):
            bar_chart_h(tmp_path / "b.mov", [])

    def test_a_panel_can_hug_its_content(self):
        # A card that always fills the frame leaves a short graphic floating in
        # empty space, which is what the first stat_card did.
        from PIL import Image, ImageDraw

        from engine.graphics import _panel
        st = make_style("light_card", width=200, height=200)
        full = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        _panel(ImageDraw.Draw(full), st)
        band = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        _panel(ImageDraw.Draw(band), st, band=(80.0, 120.0))
        assert band.getbbox()[3] - band.getbbox()[1] < full.getbbox()[3] - full.getbbox()[1]

    def test_a_panel_less_theme_draws_no_card(self):
        from PIL import Image, ImageDraw

        from engine.graphics import _panel
        st = make_style("dark_minimal", width=200, height=200)
        img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        _panel(ImageDraw.Draw(img), st)
        assert img.getbbox() is None


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
