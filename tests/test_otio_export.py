"""otio_export.py — the NLE handoff.

Skipped unless OpenTimelineIO is installed; it is an optional extra, and the
suite must stay runnable without it.

ffprobe is not available in CI either, so these tests exercise the timeline
construction directly rather than going through main(), which probes media.
"""

from __future__ import annotations

import pytest

otio = pytest.importorskip("opentimelineio", reason="optional extra: pip install -e '.[otio]'")

from otio_export import (  # noqa: E402
    SINGLE_TRACK_ADAPTERS,
    build_cut_track,
    build_overlay_track,
    time_range,
)


FPS = 30.0


@pytest.fixture
def media(tmp_path):
    p = tmp_path / "C0103.mp4"
    p.write_bytes(b"not really a video")
    return p


def edl_with_ranges(media):
    return {
        "sources": {"C0103": str(media)},
        "ranges": [
            {"source": "C0103", "start": 2.0, "end": 5.0, "beat": "HOOK",
             "quote": "the promise", "reason": "cleanest delivery"},
            {"source": "C0103", "start": 10.0, "end": 12.0, "beat": "PAYOFF",
             "quote": "the answer", "reason": "best energy"},
        ],
    }


class TestTimeRange:
    def test_seconds_convert_to_frames_at_the_timeline_rate(self):
        tr = time_range(2.0, 3.0, FPS)
        assert tr.start_time.value == 60
        assert tr.duration.value == 90


class TestCutTrack:
    def test_source_ranges_survive_the_conversion(self, tmp_path, media):
        track = build_cut_track(edl_with_ranges(media), tmp_path, FPS, {"C0103": (media, 60.0)})
        assert len(track) == 2
        assert track[0].source_range.start_time.to_seconds() == pytest.approx(2.0)
        assert track[0].source_range.duration.to_seconds() == pytest.approx(3.0)

    def test_media_reference_carries_available_range(self, tmp_path, media):
        # Without it an NLE can import the clip but cannot trim beyond the cut,
        # which defeats the point of handing over an editable timeline.
        track = build_cut_track(edl_with_ranges(media), tmp_path, FPS, {"C0103": (media, 60.0)})
        ref = track[0].media_reference
        assert ref.available_range.duration.to_seconds() == pytest.approx(60.0)
        assert ref.target_url.startswith("file://")

    def test_beats_become_markers_and_metadata(self, tmp_path, media):
        track = build_cut_track(edl_with_ranges(media), tmp_path, FPS, {"C0103": (media, 60.0)})
        assert [m.name for m in track[0].markers] == ["HOOK"]
        meta = track[0].metadata["video_use"]
        assert meta["quote"] == "the promise"
        assert meta["reason"] == "cleanest delivery"

    def test_a_range_without_a_beat_gets_no_marker(self, tmp_path, media):
        edl = edl_with_ranges(media)
        edl["ranges"][0]["beat"] = ""
        track = build_cut_track(edl, tmp_path, FPS, {"C0103": (media, 60.0)})
        assert list(track[0].markers) == []


class TestOverlayTrack:
    def test_overlays_are_gap_positioned_on_the_output_timeline(self, tmp_path):
        ov = tmp_path / "render.mp4"
        ov.write_bytes(b"x")
        track = build_overlay_track(
            [{"file": str(ov), "start_in_output": 1.5, "duration": 2.0}], tmp_path, FPS)
        kinds = [type(c).__name__ for c in track]
        assert kinds == ["Gap", "Clip"]
        assert track[0].source_range.duration.to_seconds() == pytest.approx(1.5)

    def test_an_overlap_drops_the_later_clip_rather_than_shifting_the_timeline(self, tmp_path, capsys):
        ov = tmp_path / "render.mp4"
        ov.write_bytes(b"x")
        track = build_overlay_track([
            {"file": str(ov), "start_in_output": 0.0, "duration": 3.0},
            {"file": str(ov), "start_in_output": 1.0, "duration": 2.0},
        ], tmp_path, FPS)
        assert len([c for c in track if isinstance(c, otio.schema.Clip)]) == 1
        assert "overlaps" in capsys.readouterr().out

    def test_a_zero_duration_overlay_is_refused(self, tmp_path, capsys):
        ov = tmp_path / "render.mp4"
        ov.write_bytes(b"x")
        assert build_overlay_track(
            [{"file": str(ov), "start_in_output": 0.0, "duration": 0.0}], tmp_path, FPS) is None
        assert "no duration" in capsys.readouterr().out

    def test_no_overlays_yields_no_track(self, tmp_path):
        assert build_overlay_track([], tmp_path, FPS) is None


class TestAdapterCapabilities:
    def test_cmx_3600_is_known_to_reject_multiple_tracks(self):
        # Resolved before the timeline is built; letting the write raise
        # instead was the earlier behaviour and it crashed.
        assert "cmx_3600" in SINGLE_TRACK_ADAPTERS

    def test_the_nle_adapters_are_actually_installed(self):
        available = otio.adapters.available_adapter_names()
        assert "otio_json" in available
        if "fcp_xml" not in available:
            pytest.skip("OpenTimelineIO-Plugins not installed; only core adapters present")
