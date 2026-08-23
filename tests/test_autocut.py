"""autocut.py — dead-space detection and the safety rules layered on top.

auto-editor cuts on a raw loudness threshold and has no notion of a *safe*
cut. These tests pin the two SKILL.md rules that make its output usable:
sub-150ms silences are not cuttable (Cut craft: "<150ms is unsafe"), and
sub-400ms keeps are breaths rather than speech.
"""

from __future__ import annotations

import json

from autocut import (
    KEEP_SPEED,
    apply_safety_rules,
    build_draft_edl,
    chunks_to_segments,
)


class TestChunksToSegments:
    def test_cut_chunks_are_dropped_keeps_become_seconds(self):
        chunks = [(0, 30, 99999.0), (30, 90, KEEP_SPEED), (90, 120, 99999.0), (120, 200, KEEP_SPEED)]
        assert chunks_to_segments(chunks, fps=30.0, duration=6.0) == [(1.0, 3.0), (4.0, 6.0)]

    def test_non_cut_non_normal_speed_is_ignored_not_guessed_at(self):
        # `--when-silent speed(2)` produces chunks this helper deliberately
        # does not interpret, rather than silently treating them as keeps.
        assert chunks_to_segments([(0, 30, 2.0)], 30.0, 1.0) == []

    def test_touching_chunks_merge_instead_of_making_a_zero_length_cut(self):
        # A margin wide enough to bridge a gap makes two chunks overlap.
        assert chunks_to_segments([(0, 60, KEEP_SPEED), (55, 90, KEEP_SPEED)], 30.0, 3.0) == [(0.0, 3.0)]

    def test_segments_are_clamped_to_the_source_duration(self):
        segs = chunks_to_segments([(0, 300, KEEP_SPEED)], fps=30.0, duration=5.0)
        assert segs == [(0.0, 5.0)]

    def test_empty_chunk_list(self):
        assert chunks_to_segments([], 30.0, 10.0) == []


class TestSafetyRules:
    def test_unsafely_short_silence_is_rejoined(self):
        # A 100ms gap lands mid-phrase and clips consonants — not a cut.
        assert apply_safety_rules([(1.0, 3.0), (3.1, 5.0)], min_gap=0.15, min_clip=0.4) == [(1.0, 5.0)]

    def test_comfortable_silence_stays_a_cut(self):
        segs = [(1.0, 3.0), (3.5, 5.0)]
        assert apply_safety_rules(segs, min_gap=0.15, min_clip=0.4) == segs

    def test_short_blip_is_dropped_as_breath_not_speech(self):
        assert apply_safety_rules([(1.0, 1.2), (3.0, 5.0)], min_gap=0.15, min_clip=0.4) == [(3.0, 5.0)]

    def test_merging_runs_before_dropping(self):
        # Two 200ms neighbours 100ms apart total 500ms and survive together.
        # Dropping first would discard both independently.
        assert apply_safety_rules([(1.0, 1.2), (1.3, 1.5)], min_gap=0.15, min_clip=0.4) == [(1.0, 1.5)]

    def test_empty_input(self):
        assert apply_safety_rules([], 0.15, 0.4) == []


class TestDraftEDL:
    def test_draft_edl_is_consumable_by_render(self, tmp_path):
        autocut_dir = tmp_path / "autocut"
        autocut_dir.mkdir()
        src = tmp_path / "C0103.MP4"
        src.touch()
        (autocut_dir / "C0103.json").write_text(json.dumps({
            "source": str(src),
            "segments": [
                {"start": 1.0, "end": 3.0, "duration": 2.0},
                {"start": 5.0, "end": 6.5, "duration": 1.5},
            ],
        }))

        out = tmp_path / "edl.json"
        build_draft_edl([autocut_dir / "C0103.json"], out)
        edl = json.loads(out.read_text())

        assert edl["version"] == 1
        assert edl["sources"] == {"C0103": str(src)}
        assert len(edl["ranges"]) == 2
        assert edl["total_duration_s"] == 3.5
        # Every range must carry the fields render.py reads.
        for r in edl["ranges"]:
            assert {"source", "start", "end", "beat"} <= set(r)
            assert r["source"] in edl["sources"]
            assert r["end"] > r["start"]

    def test_beats_are_tagged_auto_so_a_draft_is_never_mistaken_for_a_cut(self, tmp_path):
        autocut_dir = tmp_path / "autocut"
        autocut_dir.mkdir()
        src = tmp_path / "A.mp4"
        src.touch()
        (autocut_dir / "A.json").write_text(json.dumps({
            "source": str(src),
            "segments": [{"start": 0.0, "end": 1.0, "duration": 1.0}],
        }))
        out = tmp_path / "edl.json"
        build_draft_edl([autocut_dir / "A.json"], out)
        assert json.loads(out.read_text())["ranges"][0]["beat"] == "AUTO"
