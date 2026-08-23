"""render.py — content-bound overlay placement.

An overlay pinned to an absolute `start_in_output` drifts the moment the cut
changes, and lands on the wrong sentence. The invariant these tests defend is
the whole point of anchoring: the SAME overlay definition, resolved against a
DIFFERENT cut, follows the spoken word.
"""

from __future__ import annotations

import json

import pytest

from conftest import word
from render import (
    _normalize_token,
    build_spoken_index,
    find_occurrences,
    resolve_overlay_anchors,
)


@pytest.fixture
def edit_dir(tmp_path, make_transcript):
    make_transcript(tmp_path, "A", [
        word("Neunzig", 3.0, 3.4), word("Prozent", 3.45, 3.9),
        word("der", 3.95, 4.1), word("Arbeit", 4.15, 4.6),
        word("ist", 4.65, 4.8), word("verschwendet.", 4.85, 5.6),
    ])
    make_transcript(tmp_path, "B", [
        word("Wir", 10.0, 10.3), word("haben", 10.35, 10.7),
        word("das", 10.75, 10.9), word("behoben.", 10.95, 11.6),
        word("Neunzig", 12.0, 12.4), word("Prozent", 12.45, 12.9),
    ])
    return tmp_path


def edl_with(ranges, overlays):
    return {"sources": {"A": "a.mp4", "B": "b.mp4"}, "ranges": ranges, "overlays": overlays}


CUT_1 = [{"source": "A", "start": 2.8, "end": 6.0}, {"source": "B", "start": 9.8, "end": 13.0}]


class TestTokenNormalization:
    def test_case_and_punctuation_are_folded(self):
        # Otherwise the words most worth anchoring to — the ones ending a
        # phrase — would be the ones that fail to match.
        assert _normalize_token("Neunzig,") == "neunzig"
        assert _normalize_token("verschwendet.") == "verschwendet"
        assert _normalize_token("„Wort“") == "wort"

    def test_pure_punctuation_yields_nothing(self):
        assert _normalize_token("—") == ""


class TestSpokenIndex:
    def test_only_words_inside_a_range_are_indexed(self, edit_dir):
        # Anchoring to a word that was cut out is a mistake worth reporting,
        # not something to resolve to where the word used to be.
        idx = build_spoken_index(edl_with([{"source": "A", "start": 4.0, "end": 6.0}], []), edit_dir)
        assert "neunzig" not in [w["token"] for w in idx]
        assert "arbeit" in [w["token"] for w in idx]

    def test_output_times_use_the_segment_offset(self, edit_dir):
        idx = build_spoken_index(edl_with(CUT_1, []), edit_dir)
        by_token = {w["token"]: w for w in idx}
        # A starts at 2.8 with offset 0 -> "Neunzig" @3.0 lands at 0.20
        assert by_token["arbeit"]["output_time"] == pytest.approx(4.15 - 2.8)
        # B starts at 9.8 with offset 3.2 -> "Wir" @10.0 lands at 3.4
        assert by_token["wir"]["output_time"] == pytest.approx(10.0 - 9.8 + 3.2)

    def test_a_missing_transcript_skips_the_range_without_breaking_offsets(self, edit_dir):
        (edit_dir / "transcripts" / "A.json").unlink()
        idx = build_spoken_index(edl_with(CUT_1, []), edit_dir)
        assert [w["token"] for w in idx][:1] == ["wir"]
        # B's offset must still account for A's 3.2s, or everything after slides.
        assert idx[0]["output_time"] == pytest.approx(3.4)


class TestFindOccurrences:
    def test_repeated_word_yields_every_hit_in_cut_order(self, edit_dir):
        idx = build_spoken_index(edl_with(CUT_1, []), edit_dir)
        hits = find_occurrences(idx, "neunzig", None)
        assert len(hits) == 2
        assert hits[0]["output_time"] < hits[1]["output_time"]

    def test_source_scoping_picks_the_intended_take(self, edit_dir):
        idx = build_spoken_index(edl_with(CUT_1, []), edit_dir)
        assert len(find_occurrences(idx, "neunzig", "A")) == 1
        assert len(find_occurrences(idx, "neunzig", "B")) == 1

    def test_multi_word_phrase_matches_consecutive_tokens(self, edit_dir):
        idx = build_spoken_index(edl_with(CUT_1, []), edit_dir)
        assert len(find_occurrences(idx, "neunzig prozent", "A")) == 1
        assert find_occurrences(idx, "prozent neunzig", "A") == []

    def test_punctuated_final_word_is_reachable(self, edit_dir):
        idx = build_spoken_index(edl_with(CUT_1, []), edit_dir)
        assert find_occurrences(idx, "verschwendet", None)


class TestAnchorResolution:
    def test_the_invariant_an_anchor_survives_a_recut(self, edit_dir):
        """The reason this feature exists."""
        overlay = {"file": "slot_1/render.mp4", "anchor_word": "verschwendet",
                   "reveal_duration": 0.5, "duration": 2.0}

        first = resolve_overlay_anchors(edl_with(CUT_1, [dict(overlay)]), edit_dir)
        # "verschwendet." @4.85 in a segment starting 2.8 -> 2.05, less 0.5 reveal
        assert first[0]["start_in_output"] == pytest.approx(1.55)

        # Trim the hook by 1.2s. Everything after it shifts.
        recut = [{"source": "A", "start": 4.0, "end": 6.0}, {"source": "B", "start": 9.8, "end": 13.0}]
        second = resolve_overlay_anchors(edl_with(recut, [dict(overlay)]), edit_dir)
        assert second[0]["start_in_output"] == pytest.approx(0.35)

        # Same definition, different position — it tracked the word, not the clock.
        assert first[0]["start_in_output"] != second[0]["start_in_output"]

    def test_occurrence_selects_the_later_repeat(self, edit_dir):
        ov = {"file": "x.mp4", "anchor_word": "neunzig", "anchor_occurrence": 2, "duration": 1.0}
        out = resolve_overlay_anchors(edl_with(CUT_1, [ov]), edit_dir)
        assert out[0]["start_in_output"] == pytest.approx(12.0 - 9.8 + 3.2)

    def test_anchor_offset_nudges(self, edit_dir):
        base = {"file": "x.mp4", "anchor_word": "arbeit", "duration": 1.0}
        plain = resolve_overlay_anchors(edl_with(CUT_1, [dict(base)]), edit_dir)[0]
        nudged = resolve_overlay_anchors(
            edl_with(CUT_1, [dict(base, anchor_offset=0.25)]), edit_dir)[0]
        assert nudged["start_in_output"] == pytest.approx(plain["start_in_output"] + 0.25)

    def test_negative_start_is_clamped_to_zero(self, edit_dir, capsys):
        ov = {"file": "x.mp4", "anchor_word": "neunzig", "anchor_source": "A",
              "reveal_duration": 5.0, "duration": 1.0}
        out = resolve_overlay_anchors(edl_with(CUT_1, [ov]), edit_dir)
        assert out[0]["start_in_output"] == 0.0
        assert "clamping" in capsys.readouterr().out

    def test_legacy_absolute_overlays_pass_through_untouched(self, edit_dir):
        ov = {"file": "x.mp4", "start_in_output": 1.5, "duration": 2.0}
        assert resolve_overlay_anchors(edl_with(CUT_1, [ov]), edit_dir) == [ov]

    def test_mixed_anchored_and_absolute_overlays(self, edit_dir):
        out = resolve_overlay_anchors(edl_with(CUT_1, [
            {"file": "a.mp4", "start_in_output": 0.25, "duration": 1.0},
            {"file": "b.mp4", "anchor_word": "arbeit", "duration": 1.0},
        ]), edit_dir)
        assert out[0]["start_in_output"] == 0.25
        assert out[1]["start_in_output"] == pytest.approx(4.15 - 2.8)


class TestAnchorFailuresAreLoud:
    """A misplaced overlay is a silent failure. These must never degrade."""

    def test_word_not_in_the_cut_is_fatal(self, edit_dir):
        ov = {"file": "x.mp4", "anchor_word": "katzenfutter", "duration": 1.0}
        with pytest.raises(SystemExit) as e:
            resolve_overlay_anchors(edl_with(CUT_1, [ov]), edit_dir)
        assert "katzenfutter" in str(e.value) and "0 occurrence" in str(e.value)

    def test_occurrence_out_of_range_reports_how_many_exist(self, edit_dir):
        ov = {"file": "x.mp4", "anchor_word": "neunzig", "anchor_occurrence": 9, "duration": 1.0}
        with pytest.raises(SystemExit) as e:
            resolve_overlay_anchors(edl_with(CUT_1, [ov]), edit_dir)
        assert "2 occurrence" in str(e.value)

    def test_overlay_with_neither_field_is_caught_even_with_no_anchors_present(self, edit_dir):
        # Regression: the no-anchors early return used to skip validation, and
        # this surfaced as a bare KeyError inside the ffmpeg filter graph.
        with pytest.raises(SystemExit) as e:
            resolve_overlay_anchors(edl_with(CUT_1, [{"file": "x.mp4", "duration": 1.0}]), edit_dir)
        assert "neither" in str(e.value)

    def test_anchoring_without_any_transcript_is_fatal(self, tmp_path):
        ov = {"file": "x.mp4", "anchor_word": "irgendwas", "duration": 1.0}
        with pytest.raises(SystemExit) as e:
            resolve_overlay_anchors(edl_with(CUT_1, [ov]), tmp_path)
        assert "transcripts" in str(e.value)
