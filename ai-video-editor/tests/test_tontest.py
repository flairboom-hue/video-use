"""The room check.

Its whole job is to say "record here" or "don't" before a day of recording is
spent, so the arithmetic it says that on has to be right. The gap computation
is the part that can be quietly wrong: miss the gap before the first segment or
after the last, and a room with one long silence at the top reads as a room
with none.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import tontest  # noqa: E402


class TestGaps:
    def test_the_silence_before_the_first_word_counts(self):
        # Someone who sits down, breathes, then starts has their longest pause
        # right here. Skipping it reports a room as tighter than it is.
        assert tontest._luecken([(3.0, 5.0)], 5.0) == [(0.0, 3.0)]

    def test_the_silence_after_the_last_word_counts(self):
        assert tontest._luecken([(0.0, 2.0)], 6.0) == [(2.0, 6.0)]

    def test_gaps_between_segments_are_found(self):
        gaps = tontest._luecken([(0.0, 1.0), (2.5, 3.0), (4.0, 5.0)], 5.0)
        assert gaps == [(1.0, 2.5), (3.0, 4.0)]

    def test_speech_filling_the_whole_take_leaves_no_gap(self):
        assert tontest._luecken([(0.0, 5.0)], 5.0) == []

    def test_nothing_detected_means_the_whole_take_is_a_gap(self):
        assert tontest._luecken([], 5.0) == [(0.0, 5.0)]


class TestThresholds:
    def test_the_short_segment_bar_follows_the_cutter(self):
        # Hard-coding it would drift the moment MIN_CLIP is retuned, and the
        # advice would then contradict what the cut actually does.
        from engine import rough_cut
        assert tontest.KURZ == rough_cut.MIN_CLIP * 2

    def test_a_quiet_room_is_not_flagged_as_too_loud(self):
        # 8% is the floor. Speech with real sentence pauses sits far above it;
        # the check exists to catch rooms at 0-2%, not to grade delivery.
        assert 0 < tontest.ZU_WENIG < 15
        assert tontest.ZU_WENIG < tontest.VIEL
