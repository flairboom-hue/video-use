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


class TestMeterTrack:
    """The empty part of a bar.

    Pillow's ImageDraw replaces pixels instead of blending them, so a
    translucent track drawn over the card cuts a hole straight through it and
    the footage shows where the card should be. On a light theme that reads as
    a near-black bar — the exact opposite of "empty".
    """

    @staticmethod
    def _panel_themes():
        return [n for n in available_themes() if make_style(n, width=100, height=100).panel]

    def test_a_track_on_a_card_is_opaque(self):
        from engine.graphics import _track
        for name in self._panel_themes():
            st = make_style(name, width=100, height=100)
            assert _track(st)[3] == 255, f"{name}: translucent track punches through the card"

    def test_a_track_on_a_card_stays_near_the_card(self):
        from engine.graphics import _track
        for name in self._panel_themes():
            st = make_style(name, width=100, height=100)
            track = _track(st)[:3]
            to_panel = sum(abs(a - b) for a, b in zip(track, st.panel[:3]))
            to_muted = sum(abs(a - b) for a, b in zip(track, st.muted))
            assert to_panel < to_muted, f"{name}: empty track reads as ink, not as empty"

    def test_a_track_is_still_visible_against_the_card(self):
        # The other failure: mix it too far towards the card and the bar has
        # no visible extent at all until it fills.
        from engine.graphics import _track
        for name in self._panel_themes():
            st = make_style(name, width=100, height=100)
            spread = max(abs(a - b) for a, b in zip(_track(st)[:3], st.panel[:3]))
            assert spread >= 8, f"{name}: track is indistinguishable from the card"

    def test_strength_moves_the_track_towards_the_ink(self):
        from engine.graphics import _track
        st = make_style("light_card", width=100, height=100)
        near = sum(abs(a - b) for a, b in zip(_track(st, 0.20)[:3], st.panel[:3]))
        far = sum(abs(a - b) for a, b in zip(_track(st, 0.40)[:3], st.panel[:3]))
        assert far > near

    def test_without_a_card_the_track_is_a_translucent_tint(self):
        # Nothing to punch through, so a tint is the right answer here.
        from engine.graphics import _track
        for name in available_themes():
            st = make_style(name, width=100, height=100)
            if st.panel:
                continue
            colour = _track(st)
            assert colour[:3] == tuple(st.muted)
            assert 0 < colour[3] < 255


class TestLinkedMeters:
    """Two readouts on one control."""

    @staticmethod
    def _frame(meters, t, theme="dark_minimal", size=1000, **kw):
        """Compose a single frame without going near ffmpeg."""
        from pathlib import Path

        from PIL import Image

        from engine import graphics
        captured = {}

        def fake_render(frame, dur, st, out):
            captured["frame"] = frame
            return out

        real, graphics._render = graphics._render, fake_render
        try:
            graphics.linked_meters(Path("unused.mov"), "Ladung", meters,
                                   style=make_style(theme, width=size, height=size), **kw)
        finally:
            graphics._render = real
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        captured["frame"](ImageDraw.Draw(img), t, img)
        return img

    def test_it_is_registered(self):
        assert "linked_meters" in available_kinds()

    def test_empty_input_is_refused(self, tmp_path):
        from engine.graphics import linked_meters
        with pytest.raises(Exception):
            linked_meters(tmp_path / "x.mov", "Ladung", [])

    def test_a_meter_that_never_goes_positive_is_refused(self, tmp_path):
        # base 0, factor 0 used to divide by zero deep inside the frame
        # callback — a crash in a background job rather than a rejected input.
        from engine.graphics import GraphicsError, linked_meters
        with pytest.raises(GraphicsError):
            linked_meters(tmp_path / "x.mov", "Ladung", [("Tot", 0.0, 0.0, "")])

    def test_a_falling_meter_stays_inside_its_track(self):
        import numpy as np

        # A negative factor is the interesting coupling — one quantity bought
        # with the other. Normalising against base + factor puts the peak at
        # charge 0, which drew the bar several track-widths past the frame.
        img = self._frame([("Hoehe", 10.0, -8.0, "m"), ("Weite", 2.0, 8.0, "m")], 0.0)
        accent = make_style("dark_minimal", width=1000, height=1000).accent
        px = np.asarray(img)
        hit = (px[..., 0] == accent[0]) & (px[..., 1] == accent[1]) & (px[..., 2] == accent[2])
        assert hit.any(), "nothing was drawn in the accent colour"
        right = int(np.argwhere(hit)[:, 1].max())
        track_right = 1000 * (0.30 + 0.50)
        assert right <= track_right + 2, "the bar ran past the end of its track"
        assert right > track_right - 20, "the bar should be full at its own peak"

    def test_the_card_hugs_the_meters(self):
        # A card sized to the frame leaves a two-row diagram floating in a sea
        # of empty plate. Measured against the unbanded card rather than
        # against the frame: _panel already insets itself, so a frame-relative
        # threshold passes whether the band is honoured or not.
        from PIL import Image

        from engine.graphics import _panel
        st = make_style("light_card", width=1000, height=1000)
        unbanded = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
        _panel(ImageDraw.Draw(unbanded), st)
        full = unbanded.getbbox()[3] - unbanded.getbbox()[1]

        img = self._frame([("A", 3.0, 8.0, ""), ("B", 9.0, 15.0, "")], 1.0,
                          theme="light_card")
        drawn = img.getbbox()[3] - img.getbbox()[1]
        assert drawn < full, "the card is not sized to its content"

    def test_both_readouts_move_with_the_control(self):
        import numpy as np

        def reach(t):
            img = self._frame([("A", 3.0, 8.0, ""), ("B", 9.0, 15.0, "")], t)
            px = np.asarray(img)
            st = make_style("dark_minimal", width=1000, height=1000)
            out = []
            for colour in (st.accent, st.accent_2):
                hit = ((px[..., 0] == colour[0]) & (px[..., 1] == colour[1])
                       & (px[..., 2] == colour[2]))
                rows = np.argwhere(hit)
                out.append(int(rows[:, 1].max()) if len(rows) else 0)
            return out

        low = reach(0.0)
        high = reach(1.0)
        # The whole point of the graphic: one input, both readouts follow.
        assert high[0] > low[0] and high[1] > low[1]


class TestPlacement:
    """Where a card sits.

    Not cosmetic. A card is a full-width plate over the middle of the frame,
    which is exactly where a head is in a talking-head shot, so "centred" and
    "speaker on screen" cannot both be true.
    """

    @staticmethod
    def _bbox(placement, **kw):
        from PIL import Image

        from engine.graphics import _compose_frame, stat_card
        st = make_style("light_card", width=800, height=600, placement=placement, **kw)
        captured = {}

        def fake_render(frame, dur, s, out):
            captured["frame"] = frame
            return out

        from engine import graphics as g
        real, g._render = g._render, fake_render
        try:
            stat_card(__import__("pathlib").Path("x.mov"),
                      [("36", "Tage"), ("387", "Commits")], st)
        finally:
            g._render = real
        img = _compose_frame(captured["frame"], 1.0, st)
        assert img.size == (800, 600), "the frame is not the full canvas"
        return img.getbbox()

    def test_centred_is_exactly_what_it_was(self):
        st = make_style("light_card", width=800, height=600)
        assert st.height == 600 and st.canvas_height == 0
        assert st.reserve_caption_band is True

    def test_top_lays_the_graphic_out_in_a_band_at_the_top(self):
        st = make_style("light_card", width=800, height=600, placement="top")
        assert st.height < 600, "the graphic still uses the whole frame"
        assert st.canvas_height == 600 and st.canvas_offset_y == 0
        top, bottom = self._bbox("top")[1], self._bbox("top")[3]
        assert bottom < 600 * 0.45, "the card reaches into the middle of the frame"
        assert top < 600 * 0.2

    def test_bottom_stays_above_the_caption_band(self):
        # A card in the lower third with captions on would be crossed by every
        # subtitle, which is the failure the caption band exists to prevent.
        from engine.graphics import CAPTION_SAFE_BOTTOM
        bottom = self._bbox("bottom", reserve_caption_band=True)[3]
        assert bottom <= 600 * (1 - CAPTION_SAFE_BOTTOM) + 2

    def test_without_captions_the_bottom_band_may_reach_the_edge(self):
        with_caps = self._bbox("bottom", reserve_caption_band=True)[3]
        without = self._bbox("bottom", reserve_caption_band=False)[3]
        assert without > with_caps

    def test_the_band_is_not_reserved_twice(self):
        # The band is already placed clear of the captions; reserving again
        # inside it would shrink the graphic a second time for no reason.
        st = make_style("light_card", width=800, height=600, placement="top")
        assert st.reserve_caption_band is False
        assert st.content_height == st.height

    def test_an_unknown_placement_raises_rather_than_centring(self):
        from engine.graphics import GraphicsError
        with pytest.raises(GraphicsError):
            make_style("light_card", placement="oben")

    def test_only_implemented_placements_are_offered(self):
        from engine.graphics import PLACEMENTS, available_placements
        assert set(available_placements()) == set(PLACEMENTS)

    def test_the_type_is_relaid_rather_than_scaled_down(self):
        # Scaling a finished frame into a third of the height would soften
        # every glyph. The band gets its own, smaller layout instead.
        centred = make_style("light_card", width=800, height=600)
        placed = make_style("light_card", width=800, height=600, placement="top")
        assert placed.width == centred.width, "the card should stay full width"
        assert placed.font(int(placed.height * 0.1)).size < \
            centred.font(int(centred.height * 0.1)).size


class TestPace:
    """How fast a graphic assembles itself."""

    def test_the_default_is_the_original_timing(self):
        # Every stagger constant in this module was tuned against it; changing
        # the default would silently re-time ten generators.
        from engine.graphics import PACE_LEVELS
        st = Style()
        assert PACE_LEVELS["calm"] == (st.reveal, st.hold)
        assert st.tempo == 1.0

    def test_a_faster_pace_scales_the_staggers_too(self):
        # Shortening only the hold ends the graphic sooner without ever making
        # the entrance feel quicker — the flat part would just be cut short.
        from engine.graphics import PACE_LEVELS
        quick = Style(reveal=PACE_LEVELS["quick"][0])
        assert quick.tempo == pytest.approx(PACE_LEVELS["quick"][0] / Style().reveal)
        assert quick.tempo < 1.0

    def test_paces_are_ordered_and_all_positive(self):
        from engine.graphics import PACE_LEVELS, available_paces
        assert set(available_paces()) == set(PACE_LEVELS)
        reveals = [r for r, _ in PACE_LEVELS.values()]
        assert reveals == sorted(reveals, reverse=True)
        assert all(r > 0 and h > 0 for r, h in PACE_LEVELS.values())


class TestSpring:
    """The overshoot, and the line it is not allowed to cross."""

    def test_the_curve_is_anchored_at_both_ends(self):
        from engine.graphics import ease_out_back
        assert ease_out_back(0.0) == pytest.approx(0.0)
        assert ease_out_back(1.0) == pytest.approx(1.0)

    def test_it_actually_overshoots(self):
        from engine.graphics import ease_out_back
        assert max(ease_out_back(i / 200) for i in range(201)) > 1.05

    def test_smooth_never_exceeds_its_target(self):
        st = Style(easing="smooth")
        assert max(st.ease_move(i / 200) for i in range(201)) <= 1.0

    def test_an_unknown_easing_raises_rather_than_falling_back(self):
        from engine.graphics import GraphicsError
        with pytest.raises(GraphicsError):
            Style(easing="bounce")

    @staticmethod
    def _frames(fn, args, easing, n=6):
        """Compose a few frames without ffmpeg, for comparison."""
        from PIL import Image

        from engine import graphics as g
        st = make_style("light_card", width=320, height=180, fps=15,
                        easing=easing, reserve_caption_band=False)
        cap = {}

        def fake(frame, dur, s, out):
            cap["frame"] = frame
            return out

        real, g._render = g._render, fake
        try:
            fn(__import__("pathlib").Path("x.mov"), *args, st)
        finally:
            g._render = real
        out = []
        for i in range(n):
            img = Image.new("RGBA", (320, 180), (0, 0, 0, 0))
            cap["frame"](__import__("PIL.ImageDraw", fromlist=["ImageDraw"])
                         .Draw(img, "RGBA"), i / (n - 1), img)
            out.append(img.tobytes())
        return out

    def test_a_measured_value_never_springs(self):
        # A bar that overshoots is longer than its own measurement and a
        # counter that overshoots shows a figure the data does not contain.
        # In a video whose subject is honest numbers, that animation must not
        # be allowed to lie — so these generators ignore the setting entirely.
        from engine import graphics as g
        for fn, args in ((g.number_animation, (42, "Test", "")),
                         (g.bar_chart, ([3, 7, 5], ["a", "b", "c"])),
                         (g.pie_chart, ([30, 45, 25], None)),
                         (g.bar_chart_h, ([("a", 3), ("b", 7)],))):
            assert self._frames(fn, args, "smooth") == self._frames(fn, args, "spring"), \
                f"{fn.__name__} changed with the easing — it animates a value"

    def test_an_entrance_does_spring(self):
        # And the ones whose movement is only an entrance must actually change,
        # or the setting is a dead control.
        from engine import graphics as g
        for fn, args in ((g.stat_card, ([("36", "Tage"), ("387", "Commits")],)),
                         (g.icon_row, ([("check", "eins"), ("star", "zwei")],)),
                         (g.text_animation, ("Sieben Fehler",))):
            assert self._frames(fn, args, "smooth") != self._frames(fn, args, "spring"), \
                f"{fn.__name__} ignores the easing setting"
