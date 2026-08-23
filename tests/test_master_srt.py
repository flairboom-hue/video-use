"""render.py — Hard Rule 5: master SRT uses output-timeline offsets.

    output_time = word.start - segment_start + segment_offset

Get this wrong and captions drift further out of sync with every segment, a
failure that only shows up once someone watches the whole render. It is the
kind of bug worth pinning with arithmetic rather than eyeballing.
"""

from __future__ import annotations

import re

import pytest

from conftest import word
from render import _srt_timestamp, build_master_srt


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    """SRT back into (start, end, text) seconds, so cues can be asserted on."""
    def secs(stamp: str) -> float:
        h, m, rest = stamp.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    out = []
    for block in [b for b in text.strip().split("\n\n") if b.strip()]:
        lines = block.strip().split("\n")
        a, b = lines[1].split(" --> ")
        out.append((secs(a), secs(b), " ".join(lines[2:])))
    return out


@pytest.fixture
def edit_dir(tmp_path, make_transcript):
    make_transcript(tmp_path, "A", [
        word("Neunzig", 10.0, 10.4), word("Prozent", 10.5, 11.0),
        word("der", 11.1, 11.2), word("Arbeit", 11.3, 11.8),
    ])
    make_transcript(tmp_path, "B", [
        word("Wir", 30.0, 30.3), word("haben", 30.4, 30.8),
        word("das", 30.9, 31.0), word("behoben", 31.1, 31.6),
    ])
    return tmp_path


class TestTimestampFormatting:
    def test_srt_timestamp_shape(self):
        assert _srt_timestamp(0.0) == "00:00:00,000"
        assert _srt_timestamp(3661.5) == "01:01:01,500"

    def test_every_cue_uses_comma_milliseconds(self, edit_dir, tmp_path):
        edl = {"sources": {"A": "a.mp4"}, "ranges": [{"source": "A", "start": 9.9, "end": 12.0}]}
        out = tmp_path / "master.srt"
        build_master_srt(edl, edit_dir, out)
        for stamp in re.findall(r"\d\d:\d\d:\d\d[,.]\d\d\d", out.read_text()):
            assert "," in stamp, "SRT requires a comma, not a period"


class TestOutputTimelineMath:
    def test_first_segment_offsets_from_its_own_start(self, edit_dir, tmp_path):
        edl = {"sources": {"A": "a.mp4"}, "ranges": [{"source": "A", "start": 9.9, "end": 12.0}]}
        out = tmp_path / "master.srt"
        build_master_srt(edl, edit_dir, out)
        cues = parse_srt(out.read_text())
        # "Neunzig" @10.0 in a segment starting 9.9 -> 0.1s on the output timeline
        assert cues[0][0] == pytest.approx(0.1, abs=1e-3)

    def test_second_segment_is_shifted_by_the_first_segments_duration(self, edit_dir, tmp_path):
        edl = {"sources": {"A": "a.mp4", "B": "b.mp4"}, "ranges": [
            {"source": "A", "start": 9.9, "end": 12.0},    # 2.1s long
            {"source": "B", "start": 29.9, "end": 32.0},
        ]}
        out = tmp_path / "master.srt"
        build_master_srt(edl, edit_dir, out)
        cues = parse_srt(out.read_text())
        wir = next(c for c in cues if "WIR" in c[2])
        # "Wir" @30.0, segment starts 29.9, offset 2.1 -> 2.2
        assert wir[0] == pytest.approx(2.2, abs=1e-3)

    def test_cues_never_run_past_the_rendered_duration(self, edit_dir, tmp_path):
        ranges = [{"source": "A", "start": 9.9, "end": 12.0},
                  {"source": "B", "start": 29.9, "end": 32.0}]
        edl = {"sources": {"A": "a.mp4", "B": "b.mp4"}, "ranges": ranges}
        out = tmp_path / "master.srt"
        build_master_srt(edl, edit_dir, out)
        total = sum(r["end"] - r["start"] for r in ranges)
        assert all(end <= total + 1e-6 for _, end, _ in parse_srt(out.read_text()))

    def test_cues_are_ordered_and_non_degenerate(self, edit_dir, tmp_path):
        edl = {"sources": {"A": "a.mp4", "B": "b.mp4"}, "ranges": [
            {"source": "A", "start": 9.9, "end": 12.0},
            {"source": "B", "start": 29.9, "end": 32.0},
        ]}
        out = tmp_path / "master.srt"
        build_master_srt(edl, edit_dir, out)
        cues = parse_srt(out.read_text())
        assert cues == sorted(cues, key=lambda c: c[0])
        assert all(end > start for start, end, _ in cues)


class TestCaptionStyle:
    def test_chunks_are_at_most_two_words_and_uppercase(self, edit_dir, tmp_path):
        edl = {"sources": {"A": "a.mp4"}, "ranges": [{"source": "A", "start": 9.9, "end": 12.0}]}
        out = tmp_path / "master.srt"
        build_master_srt(edl, edit_dir, out)
        for _, _, text in parse_srt(out.read_text()):
            assert len(text.split()) <= 2
            assert text == text.upper()

    def test_a_missing_transcript_skips_captions_but_keeps_the_offset(self, edit_dir, tmp_path, capsys):
        edl = {"sources": {"A": "a.mp4", "B": "b.mp4"}, "ranges": [
            {"source": "MISSING", "start": 0.0, "end": 5.0},
            {"source": "B", "start": 29.9, "end": 32.0},
        ]}
        out = tmp_path / "master.srt"
        build_master_srt(edl, edit_dir, out)
        assert "no transcript" in capsys.readouterr().out
        wir = next(c for c in parse_srt(out.read_text()) if "WIR" in c[2])
        # The 5s gap must still be counted, or B's captions land 5s early.
        assert wir[0] == pytest.approx(0.1 + 5.0, abs=1e-3)
