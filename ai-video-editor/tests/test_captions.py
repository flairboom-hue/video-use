"""Caption timing on the output timeline, and the platform safe zone."""
from __future__ import annotations

import pytest

from engine.captions import STYLES, build_ass, play_res_for, words_on_output_timeline
from engine.transcribe import Transcript, Word


def T(*triples) -> Transcript:
    return Transcript(words=[Word(t, s, e) for t, s, e in triples])


class TestOutputTimeline:
    def test_first_clip_offsets_from_its_own_start(self):
        t = T(("Der", 10.0, 10.3))
        assert words_on_output_timeline(t, [(9.9, 11.0)])[0].start == pytest.approx(0.1)

    def test_second_clip_is_shifted_by_the_first_clip_duration(self):
        # Getting this wrong drifts captions further out with every clip.
        t = T(("Der", 10.0, 10.3), ("Wir", 30.0, 30.3))
        out = words_on_output_timeline(t, [(9.9, 11.0), (29.9, 31.0)])
        assert out[1].start == pytest.approx(30.0 - 29.9 + 1.1)

    def test_words_outside_every_clip_are_dropped(self):
        t = T(("drin", 10.0, 10.3), ("draussen", 20.0, 20.3))
        out = words_on_output_timeline(t, [(9.9, 11.0)])
        assert [w.text for w in out] == ["drin"]

    def test_a_word_straddling_a_cut_is_clipped_to_it(self):
        t = T(("lang", 10.0, 12.0))
        out = words_on_output_timeline(t, [(9.9, 11.0)])
        assert out[0].end == pytest.approx(1.1)


class TestPlayRes:
    def test_portrait_keeps_full_height_so_margin_v_lands_low(self):
        # libass measures MarginV against PlayResY. A square PlayRes on a 9:16
        # frame pushes captions to the middle, into the picture.
        assert play_res_for(1080, 1920) == (162, 288)

    def test_landscape_keeps_full_width(self):
        assert play_res_for(1920, 1080) == (288, 162)

    def test_square(self):
        assert play_res_for(1080, 1080) == (288, 288)

    def test_degenerate_input_does_not_divide_by_zero(self):
        assert play_res_for(0, 0) == (288, 288)


class TestAss:
    def test_karaoke_style_emits_per_word_timing(self, tmp_path):
        words = [Word("Der", 0.0, 0.3), Word("Umsatz", 0.35, 0.9)]
        p = build_ass(words, STYLES["word_highlight"], tmp_path / "c.ass")
        line = next(l for l in p.read_text().splitlines() if l.startswith("Dialogue"))
        assert line.count("\\k") == 2

    def test_uppercase_is_applied_when_the_style_asks(self, tmp_path):
        p = build_ass([Word("leise", 0.0, 0.4)], STYLES["bold_center"], tmp_path / "c.ass")
        assert "LEISE" in p.read_text()

    def test_braces_cannot_inject_ass_override_tags(self, tmp_path):
        p = build_ass([Word("{\\an8}x", 0.0, 0.4)], STYLES["clean_lower"], tmp_path / "c.ass")
        body = next(l for l in p.read_text().splitlines() if l.startswith("Dialogue"))
        assert "{\\an8}" not in body

    def test_zero_length_cue_gets_a_minimum_duration(self, tmp_path):
        p = build_ass([Word("x", 1.0, 1.0)], STYLES["big_impact"], tmp_path / "c.ass")
        line = next(l for l in p.read_text().splitlines() if l.startswith("Dialogue"))
        start, end = line.split(",")[1], line.split(",")[2]
        assert start != end
