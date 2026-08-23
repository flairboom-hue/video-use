"""Pre-export quality control.

The point is not to produce a report — it is to refuse to ship a broken file.
Each check returns a severity and, where it can, a concrete remedy. `blocking`
findings stop the export; warnings are shown and can be overridden.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

BLACK_FRACTION_LIMIT = 0.10     # >10% of runtime black is a broken render
SILENCE_FRACTION_LIMIT = 0.90
MIN_LUFS, MAX_LUFS = -20.0, -9.0


@dataclass
class Finding:
    check: str
    severity: str        # ok | warning | blocking
    message: str
    remedy: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _ffprobe_json(path: Path) -> dict:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True)
    return json.loads(p.stdout) if p.returncode == 0 else {}


def check(video: Path, expect_duration: float | None = None,
          expect_size: tuple[int, int] | None = None,
          captions: Path | None = None,
          assets: list[Path] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    video = Path(video)

    if not video.exists() or video.stat().st_size == 0:
        return [Finding("file", "blocking", f"{video.name} was not produced",
                        "Re-run the render and read the ffmpeg error.")]

    data = _ffprobe_json(video)
    if not data:
        return [Finding("readable", "blocking", "ffprobe cannot read the output",
                        "The render produced a corrupt file — re-render.")]

    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or 0.0)

    # -- presence ----------------------------------------------------------
    findings.append(Finding("video_stream", "ok", "video stream present") if v else
                    Finding("video_stream", "blocking", "no video stream",
                            "The render dropped the video — check the filter graph."))
    findings.append(Finding("audio_stream", "ok", "audio stream present") if a else
                    Finding("audio_stream", "warning", "no audio stream",
                            "Intentional for a silent piece; otherwise check the source."))

    # -- geometry and timing ----------------------------------------------
    if v:
        w, h = int(v.get("width") or 0), int(v.get("height") or 0)
        fps = _rate(v.get("avg_frame_rate"))
        if expect_size and (w, h) != tuple(expect_size):
            findings.append(Finding(
                "resolution", "blocking", f"expected {expect_size[0]}x{expect_size[1]}, got {w}x{h}",
                "The export preset and the render spec disagree."))
        else:
            findings.append(Finding("resolution", "ok", f"{w}x{h}"))
        findings.append(Finding("fps", "ok", f"{fps:.2f} fps") if fps > 0 else
                        Finding("fps", "warning", "frame rate unreadable", ""))

    if expect_duration and duration:
        drift = abs(duration - expect_duration)
        if drift > max(0.5, expect_duration * 0.02):
            findings.append(Finding(
                "duration", "warning",
                f"{duration:.2f}s rendered vs {expect_duration:.2f}s planned "
                f"(drift {drift:.2f}s)",
                "Small drift is frame rounding; a large one means clips were dropped."))
        else:
            findings.append(Finding("duration", "ok", f"{duration:.2f}s"))

    # -- black frames ------------------------------------------------------
    black = _black_seconds(video)
    if duration and black / duration > BLACK_FRACTION_LIMIT:
        findings.append(Finding(
            "black_frames", "blocking",
            f"{black:.1f}s of {duration:.1f}s is black ({black / duration * 100:.0f}%)",
            "Usually a bad cut range or a failed overlay. Check the timeline."))
    elif black > 0.5:
        findings.append(Finding("black_frames", "warning", f"{black:.1f}s of black detected", ""))
    else:
        findings.append(Finding("black_frames", "ok", "no significant black frames"))

    # -- loudness ----------------------------------------------------------
    if a:
        lufs = _loudness(video)
        if lufs is None:
            findings.append(Finding("loudness", "warning", "could not measure loudness", ""))
        elif not (MIN_LUFS <= lufs <= MAX_LUFS):
            findings.append(Finding(
                "loudness", "warning", f"{lufs:.1f} LUFS is outside the target band",
                "Platforms normalise to about -14 LUFS. Re-run normalisation."))
        else:
            findings.append(Finding("loudness", "ok", f"{lufs:.1f} LUFS"))

    # -- captions ----------------------------------------------------------
    if captions:
        findings.append(_check_captions(Path(captions), duration))

    # -- assets ------------------------------------------------------------
    missing = [str(p) for p in (assets or []) if not Path(p).exists()]
    findings.append(Finding("assets", "blocking",
                            f"{len(missing)} referenced asset(s) missing: {missing[:3]}",
                            "Restore the files or remove them from the timeline.")
                    if missing else Finding("assets", "ok", "all assets present"))

    return findings


def _rate(raw: str | None) -> float:
    if not raw:
        return 0.0
    n, _, d = raw.partition("/")
    try:
        return float(n) / float(d or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _black_seconds(video: Path) -> float:
    p = subprocess.run(
        ["ffmpeg", "-i", str(video), "-vf", "blackdetect=d=0.4:pix_th=0.10",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True)
    return sum(float(m) for m in re.findall(r"black_duration:(\d+\.?\d*)", p.stderr))


def _loudness(video: Path) -> float | None:
    p = subprocess.run(
        ["ffmpeg", "-i", str(video), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if not m:
        return None
    try:
        return float(json.loads(m.group(0))["input_i"])
    except (ValueError, KeyError):
        return None


def _check_captions(path: Path, duration: float) -> Finding:
    if not path.exists():
        return Finding("captions", "warning", "caption file missing", "Rebuild captions.")
    stamps = re.findall(r"(\d+):(\d\d):(\d\d[.,]\d+)", path.read_text(encoding="utf-8"))
    if not stamps:
        return Finding("captions", "warning", "caption file has no cues", "")
    last = max(int(h) * 3600 + int(m) * 60 + float(s.replace(",", "."))
               for h, m, s in stamps)
    if duration and last > duration + 1.0:
        return Finding("captions", "blocking",
                       f"captions run to {last:.1f}s but the video is {duration:.1f}s",
                       "The caption track was built against a different cut — rebuild it.")
    return Finding("captions", "ok", f"{len(stamps) // 2} cues, ends at {last:.1f}s")


def verdict(findings: list[Finding]) -> dict:
    blocking = [f for f in findings if f.severity == "blocking"]
    warnings = [f for f in findings if f.severity == "warning"]
    return {
        "can_export": not blocking,
        "blocking": [f.to_dict() for f in blocking],
        "warnings": [f.to_dict() for f in warnings],
        "checks": [f.to_dict() for f in findings],
    }
