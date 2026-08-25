"""Before/after wipes.

The pixels are checked by looking at rendered frames; what belongs here is the
arithmetic that decides where the seam is and how long each side runs. Those
are the parts that fail quietly: a divider drawn beside the seam instead of on
it still renders, still plays, and just looks broken.
"""
from __future__ import annotations

import shutil

import pytest

from engine import compare
from engine.compare import CompareError, CompareSpec, is_image, split_expr

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


class TestSpec:
    def test_duration_is_the_two_holds_plus_the_sweep(self):
        assert CompareSpec(0.8, 1.6, 1.4).duration == pytest.approx(3.8)

    def test_a_sweep_of_zero_is_refused(self):
        # It would divide by zero in the seam expression and render a hard cut.
        with pytest.raises(CompareError):
            CompareSpec(hold_before=1.0, sweep=0.0).validate()

    def test_a_negative_hold_is_refused(self):
        with pytest.raises(CompareError):
            CompareSpec(hold_before=-1.0).validate()

    def test_holds_may_be_zero(self):
        CompareSpec(hold_before=0.0, sweep=1.0, hold_after=0.0).validate()


class TestSeamPosition:
    """The expression both the wipe and the divider are driven from."""

    @staticmethod
    def _at(expr: str, t: float, width: float = 1000.0) -> float:
        # Evaluate ffmpeg's expression the way ffmpeg would.
        def clip(x, lo, hi):
            return max(lo, min(hi, x))
        return eval(expr.replace("W", str(width)).replace("t", str(t)),  # noqa: S307
                    {"clip": clip})

    def test_it_starts_at_the_right_edge_and_ends_at_the_left(self):
        # The new state sweeps in from the right, which is what puts "vorher"
        # on the left in reading order.
        spec = CompareSpec(0.8, 1.6, 1.4)
        expr = split_expr(spec, "W", "t")
        assert self._at(expr, 0.0) == pytest.approx(1000.0)
        assert self._at(expr, 3.8) == pytest.approx(0.0)

    def test_it_is_still_during_both_holds(self):
        # Without the clamp the seam would keep travelling past the frame and
        # the divider would sit outside it.
        spec = CompareSpec(0.8, 1.6, 1.4)
        expr = split_expr(spec, "W", "t")
        assert self._at(expr, 0.0) == pytest.approx(self._at(expr, 0.79))
        assert self._at(expr, 2.4) == pytest.approx(0.0, abs=1e-9)
        assert self._at(expr, 3.8) == pytest.approx(0.0, abs=1e-9)

    def test_it_is_halfway_at_the_middle_of_the_sweep(self):
        spec = CompareSpec(1.0, 2.0, 1.0)
        assert self._at(split_expr(spec, "W", "t"), 2.0) == pytest.approx(500.0)

    def test_both_filters_get_the_same_formula(self):
        # blend/xfade name the width W, drawbox and overlay name it iw. Two
        # copies of this formula drifting apart would draw the line beside the
        # seam, which is why it lives in one function.
        spec = CompareSpec(0.5, 1.0, 0.5)
        assert (split_expr(spec, "W", "t").replace("W", "X", 1)
                == split_expr(spec, "iw", "t").replace("iw", "X", 1))


class TestInputHandling:
    def test_stills_and_clips_are_told_apart_by_extension(self):
        assert is_image("shot.PNG") and is_image("a/b/frame.jpeg")
        assert not is_image("clip.mp4") and not is_image("clip.mov")

    def test_a_still_is_looped_to_length(self):
        args = compare._input_args(compare.Path("x.png"), 2.5)
        assert "-loop" in args and "2.500" in args

    def test_a_clip_shorter_than_the_wipe_is_looped_too(self):
        # Otherwise a one-second clip ends the comparison one second in.
        args = compare._input_args(compare.Path("x.mp4"), 2.5)
        assert "-stream_loop" in args and "2.500" in args

    def test_each_side_is_read_through_the_whole_sweep(self, tmp_path, monkeypatch):
        # Cut the "before" at its hold and xfade has nothing left to wipe away:
        # the clip comes out short, entirely in the "after" state, with no wipe
        # and no error. Checked against ffmpeg before it was pinned here.
        from PIL import Image
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            (tmp_path / "o.mov").write_bytes(b"x")
            return type("P", (), {"returncode": 0, "stderr": ""})()

        for name in ("a.png", "b.png"):
            Image.new("RGB", (8, 8), (1, 2, 3)).save(tmp_path / name)
        monkeypatch.setattr(compare.subprocess, "run", fake_run)

        spec = CompareSpec(0.5, 1.0, 0.7)
        compare.build_comparison(tmp_path / "a.png", tmp_path / "b.png",
                                 tmp_path / "o.mov", "v", "n", None, spec)
        cmd = seen["cmd"]
        lengths = [float(cmd[i + 1]) for i, a in enumerate(cmd) if a == "-t"]
        assert lengths[0] >= spec.hold_before + spec.sweep - 1e-6
        assert lengths[1] >= spec.sweep + spec.hold_after - 1e-6

    def test_a_missing_file_is_named(self, tmp_path):
        real = tmp_path / "there.png"
        real.write_bytes(b"x")
        with pytest.raises(CompareError) as exc:
            compare.build_comparison(tmp_path / "gone.png", real, tmp_path / "o.mov")
        assert "before" in str(exc.value) and "gone.png" in str(exc.value)


@needs_ffmpeg
class TestRendered:
    """A wipe that renders is not the same as a wipe that is right."""

    SPEC = CompareSpec(0.4, 0.8, 0.4)

    def _wipe(self, tmp_path, before=(200, 40, 40), after=(40, 40, 200),
              labels=("", ""), name="w"):
        from PIL import Image

        from engine import graphics as gfx
        a, b = tmp_path / f"{name}a.png", tmp_path / f"{name}b.png"
        Image.new("RGB", (640, 360), before).save(a)
        Image.new("RGB", (640, 360), after).save(b)
        st = gfx.Style(width=320, height=180, fps=15, reserve_caption_band=False)
        return compare.build_comparison(a, b, tmp_path / f"{name}.mov", *labels,
                                        st, self.SPEC)

    @staticmethod
    def _frame(clip, tmp_path, t):
        import subprocess

        from PIL import Image
        png = tmp_path / f"f{t}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", str(clip),
                        "-frames:v", "1", "-update", "1", str(png)], check=True)
        return Image.open(png).convert("RGB")

    @staticmethod
    def _is_before(px):
        return px[0] > px[2]

    def test_the_clip_is_as_long_as_the_spec_says(self, tmp_path):
        from engine import media
        out = self._wipe(tmp_path)
        assert media.probe(out).duration == pytest.approx(self.SPEC.duration, abs=0.15)

    def test_each_hold_shows_its_own_state(self, tmp_path):
        out = self._wipe(tmp_path)
        opening = self._frame(out, tmp_path, 0.1).getpixel((160, 90))
        closing = self._frame(out, tmp_path, 1.5).getpixel((160, 90))
        # A wipe that runs backwards is still a valid render and a wrong
        # statement, so the direction is asserted, not just the movement.
        assert self._is_before(opening), "the opening hold is not the before state"
        assert not self._is_before(closing), "the closing hold is not the after state"

    def test_during_the_sweep_the_before_state_is_on_the_left(self, tmp_path):
        # Not cosmetic: the labels are pinned to the sides, so a reversed wipe
        # captions the fixed version "vorher".
        out = self._wipe(tmp_path)
        mid = self._frame(out, tmp_path, self.SPEC.hold_before + self.SPEC.sweep / 2)
        assert self._is_before(mid.getpixel((30, 90))), "left of the seam is not the before state"
        assert not self._is_before(mid.getpixel((290, 90))), "right of the seam is not the after state"

    def test_the_divider_only_exists_while_the_seam_moves(self, tmp_path):
        # Left up through the holds it is a stray marked line parked against an
        # edge of an otherwise clean frame.
        #
        # Two near-white shades, so the only dark pixels in the row can be the
        # divider: between two saturated colours the chroma smear at the seam
        # would answer for it and the test would pass with no divider at all.
        clip = self._wipe(tmp_path, (240, 240, 240), (200, 200, 200), name="d")

        def marker_pixels(t):
            img = self._frame(clip, tmp_path, t)
            row = [img.getpixel((x, 90)) for x in range(img.width)]
            return sum(1 for c in row if sum(c) / 3 < 150)

        assert marker_pixels(self.SPEC.hold_before + self.SPEC.sweep / 2) >= 4
        assert marker_pixels(self.SPEC.duration - 0.1) == 0


class TestPlacement:
    """Where a comparison lands, decided before anything is rendered."""

    @staticmethod
    def _project(tmp_path, with_transcript=False):
        from engine.project import Project
        src = tmp_path / "take.mp4"
        src.write_bytes(b"x")
        p = Project.create(tmp_path / "projects", src)
        if with_transcript:
            d = p.root / "transcripts"
            d.mkdir(parents=True, exist_ok=True)
            (d / "take.json").write_text('{"words": []}')
        return p

    def test_neither_an_anchor_nor_a_timestamp_is_refused(self, tmp_path):
        from engine import pipeline
        with pytest.raises(ValueError):
            pipeline.check_comparison_placement(self._project(tmp_path), "", None)

    def test_an_anchor_without_a_transcript_is_refused_with_the_way_out(self, tmp_path):
        # The renderer drops an overlay whose anchor it cannot resolve, and
        # says nothing. Refusing here is the difference between a message and
        # a comparison that is simply missing from the export.
        from engine import pipeline
        with pytest.raises(ValueError) as exc:
            pipeline.check_comparison_placement(self._project(tmp_path), "Berge", None)
        assert "start_in_output" in str(exc.value) and "Berge" in str(exc.value)

    def test_an_anchor_with_a_transcript_is_accepted(self, tmp_path):
        from engine import pipeline
        pipeline.check_comparison_placement(
            self._project(tmp_path, with_transcript=True), "Berge", None)

    def test_a_timestamp_needs_no_transcript(self, tmp_path):
        from engine import pipeline
        pipeline.check_comparison_placement(self._project(tmp_path), "", 4.0)

    def test_zero_seconds_is_a_position_not_a_missing_value(self, tmp_path):
        # `if start_in_output` instead of `is not None` treats the very start
        # of the video as "no position given". Asserted with an anchor word as
        # well, because without one the earlier branch returns first and the
        # confusion never gets a chance to show.
        from engine import pipeline
        pipeline.check_comparison_placement(self._project(tmp_path), "", 0.0)
        pipeline.check_comparison_placement(self._project(tmp_path), "Berge", 0.0)
