"""The rough cut removes the right things and, more importantly, not the wrong ones."""
from __future__ import annotations

from engine.rough_cut import (_intersect, _invert, apply_safety, detect_false_starts,
                              detect_fillers, detect_repetitions)
from engine.transcribe import Transcript, Word


def T(*triples) -> Transcript:
    return Transcript(words=[Word(t, s, e) for t, s, e in triples], language="de")


class TestFillers:
    def test_hard_filler_is_removed(self):
        t = T(("Ähm", 0.0, 0.3), ("wir", 0.4, 0.6), ("haben", 0.65, 0.9))
        assert [r.detail for r in detect_fillers(t)] == ["Ähm"]

    def test_contextual_word_mid_sentence_is_grammar_not_filler(self):
        # Cutting "also" out of a flowing clause breaks the sentence.
        t = T(("das", 0.95, 1.1), ("also", 1.15, 1.35), ("behoben", 1.4, 1.9))
        assert detect_fillers(t) == []

    def test_contextual_word_between_pauses_is_a_filler(self):
        t = T(("Wir", 0.0, 0.3), ("also", 1.0, 1.3), ("haben", 2.0, 2.3))
        assert [r.detail for r in detect_fillers(t)] == ["also"]

    def test_english_vocabulary_is_always_active(self):
        t = T(("uh", 0.0, 0.2), ("yes", 0.3, 0.6))
        assert [r.detail for r in detect_fillers(t, "de")] == ["uh"]


class TestRepetitions:
    def test_retake_drops_the_first_attempt(self):
        # The speaker restarted; the second attempt is the one they chose to keep.
        t = T(("Der", 0.0, 0.2), ("Umsatz", 0.25, 0.7), ("stieg", 0.75, 1.0),
              ("Der", 1.5, 1.7), ("Umsatz", 1.75, 2.2), ("stieg", 2.25, 2.5))
        out = detect_repetitions(t)
        assert len(out) == 1
        assert out[0].start == 0.0 and out[0].end == 1.0

    def test_a_distant_repeat_is_a_callback_not_a_retake(self):
        t = T(("Der", 0.0, 0.2), ("Umsatz", 0.25, 0.7), ("stieg", 0.75, 1.0),
              ("Der", 30.0, 30.2), ("Umsatz", 30.25, 30.7), ("stieg", 30.75, 31.0))
        assert detect_repetitions(t) == []


class TestFalseStarts:
    def test_abandoned_fragment_before_a_restart(self):
        t = T(("Wir", 0.0, 0.2), ("haben", 0.25, 0.5),
              ("Wir", 1.4, 1.6), ("haben", 1.65, 1.9), ("das", 1.95, 2.1),
              ("behoben.", 2.15, 2.6))
        assert len(detect_false_starts(t)) == 1

    def test_a_finished_sentence_is_not_a_false_start(self):
        t = T(("Wir", 0.0, 0.2), ("gewannen.", 0.25, 0.8),
              ("Dann", 1.5, 1.8), ("kam", 1.85, 2.1), ("mehr.", 2.15, 2.6))
        assert detect_false_starts(t) == []


class TestSafetyRules:
    def test_sub_threshold_silence_is_not_cuttable(self):
        assert apply_safety([(1.0, 3.0), (3.1, 5.0)]) == [(1.0, 5.0)]

    def test_a_clean_silence_stays_a_cut(self):
        assert apply_safety([(1.0, 3.0), (3.5, 5.0)]) == [(1.0, 3.0), (3.5, 5.0)]

    def test_breath_length_fragments_are_dropped(self):
        assert apply_safety([(1.0, 1.2), (3.0, 5.0)]) == [(3.0, 5.0)]

    def test_merging_runs_before_dropping(self):
        # Two 200ms neighbours 100ms apart total 500ms and survive together.
        assert apply_safety([(1.0, 1.2), (1.3, 1.5)]) == [(1.0, 1.5)]


class TestRangeMath:
    def test_invert(self):
        assert _invert([(2.0, 3.0)], 10.0) == [(0.0, 2.0), (3.0, 10.0)]

    def test_invert_clamps_to_duration(self):
        assert _invert([(8.0, 99.0)], 10.0) == [(0.0, 8.0)]

    def test_intersect(self):
        assert _intersect([(0, 10)], [(2, 4), (6, 8)]) == [(2, 4), (6, 8)]
