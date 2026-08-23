"""Detect dead space in a source with auto-editor and emit keep-ranges.

Wraps https://github.com/WyattBlue/auto-editor as a *cut-candidate generator*,
not as a renderer. auto-editor analyses the audio track and reports which
frame ranges are "loud"; this helper converts those to second-precision
keep-ranges, applies the video-use safety rules, and writes them to
<edit_dir>/autocut/<video_stem>.json.

Nothing is re-encoded here. The output is a proposal the editor reads before
picking takes — it removes the mechanical work (silence, dead air between
takes) so take selection and beat ordering stay a judgement call.

Why the post-processing exists: auto-editor cuts on a raw loudness threshold
and has no notion of a *safe* cut. Two rules from SKILL.md are applied on top:

  - Silences shorter than --min-gap are NOT cut. Sub-150ms gaps land
    mid-phrase and clip consonants (Cut craft: "<150ms is unsafe").
  - Kept segments shorter than --min-clip are dropped. These are breaths,
    lip smacks and mic bumps that cleared the threshold, not speech.

--margin is auto-editor's cut padding and maps directly onto Hard Rule 7's
30-200ms working window. The default 0.05s,0.08s is the padding the launch
video shipped with (50ms before the first kept word, 80ms after the last).

Cached: if the output file already exists, the analysis is skipped (--force
to re-run).

Usage:
    python helpers/autocut.py <video_path>
    python helpers/autocut.py <videos_dir>
    python helpers/autocut.py <video_path> --margin 0.1s,0.15s
    python helpers/autocut.py <video_path> --threshold 0.06
    python helpers/autocut.py <video_path> --min-gap 0.4 --min-clip 0.5
    python helpers/autocut.py <videos_dir> --edl edit/edl_draft.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


VIDEO_EXTS = {".mp4", ".MP4", ".mov", ".MOV", ".mkv", ".MKV", ".avi", ".AVI", ".m4v"}

# auto-editor marks cut chunks with a sentinel speed of 99999. Anything at
# normal speed is a keep; a --when-silent speed(N) run would produce other
# values, which this helper deliberately ignores rather than guessing at.
KEEP_SPEED = 1.0

# auto-editor colours its diagnostics; the codes are noise in a log file.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# Not a failure: it is what auto-editor says when the threshold left nothing
# loud. A silent source in a batch of takes is a result, not a crash.
EMPTY_TIMELINE = "timeline is empty"


def require_auto_editor() -> str:
    exe = shutil.which("auto-editor")
    if not exe:
        sys.exit(
            "auto-editor not found on PATH.\n"
            "Install it with:  pip install auto-editor\n"
            "(or `uv pip install auto-editor` inside the video-use repo)"
        )
    return exe


def probe_fps(video: Path) -> float:
    """Average frame rate of the first video stream.

    auto-editor reports chunk boundaries in frames at the source timebase, so
    this is what converts them back to seconds.
    """
    for key in ("avg_frame_rate", "r_frame_rate"):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", f"stream={key}",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True, check=True,
        )
        raw = out.stdout.strip()
        num, _, den = raw.partition("/")
        try:
            fps = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            continue
        if fps > 0:
            return fps
    raise RuntimeError(
        f"no usable frame rate on {video.name} — is there a video stream?"
    )


def probe_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def run_auto_editor(
    video: Path,
    exe: str,
    margin: str,
    threshold: float | None,
) -> list[tuple[int, int, float]]:
    """Run auto-editor in analysis-only mode. Returns its raw chunk list.

    The `v1` export is a plain [start_frame, end_frame, speed] list — the most
    stable of auto-editor's export schemas and the only one that survives
    version drift without field-name guessing. No media is written.
    """
    cmd = [exe, str(video), "--export", "v1", "--margin", margin, "--no-open", "-q"]
    if threshold is not None:
        cmd += ["--edit", f"audio:threshold={threshold}"]

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "chunks.v1"
        proc = subprocess.run(
            cmd + ["-o", str(out_path)], capture_output=True, text=True,
        )
        if proc.returncode != 0 or not out_path.exists():
            detail = ANSI_RE.sub("", proc.stderr or proc.stdout).strip()
            if EMPTY_TIMELINE in detail.lower():
                return []
            raise RuntimeError(f"auto-editor failed on {video.name}: {detail[:500]}")
        payload = json.loads(out_path.read_text())

    return [(int(c[0]), int(c[1]), float(c[2])) for c in payload["chunks"]]


def chunks_to_segments(
    chunks: list[tuple[int, int, float]],
    fps: float,
    duration: float,
) -> list[tuple[float, float]]:
    """Keep-chunks → merged (start, end) second ranges, clamped to the source."""
    segments: list[tuple[float, float]] = []
    for start_f, end_f, speed in chunks:
        if speed != KEEP_SPEED:
            continue
        start = max(0.0, start_f / fps)
        end = min(duration, end_f / fps)
        if end <= start:
            continue
        # auto-editor emits chunks in order and never overlapping, but a
        # margin wide enough to bridge a gap can make two of them touch.
        if segments and start <= segments[-1][1]:
            segments[-1] = (segments[-1][0], max(segments[-1][1], end))
        else:
            segments.append((start, end))
    return segments


def apply_safety_rules(
    segments: list[tuple[float, float]],
    min_gap: float,
    min_clip: float,
) -> list[tuple[float, float]]:
    """Re-join unsafely short silences, then drop sub-threshold blips.

    Order matters: merging first lets two short neighbours separated by a
    hairline gap add up to one segment that clears min_clip, instead of both
    being discarded independently.
    """
    if not segments:
        return []

    merged: list[list[float]] = [list(segments[0])]
    for start, end in segments[1:]:
        if start - merged[-1][1] < min_gap:
            merged[-1][1] = end
        else:
            merged.append([start, end])

    return [(s, e) for s, e in merged if e - s >= min_clip]


def analyze_one(
    video: Path,
    edit_dir: Path,
    exe: str,
    margin: str = "0.05s,0.08s",
    threshold: float | None = None,
    min_gap: float = 0.15,
    min_clip: float = 0.4,
    force: bool = False,
    verbose: bool = True,
) -> Path:
    """Analyse a single video. Returns path to the autocut JSON.

    Cached: returns the existing path immediately unless force=True.
    """
    autocut_dir = edit_dir / "autocut"
    autocut_dir.mkdir(parents=True, exist_ok=True)
    out_path = autocut_dir / f"{video.stem}.json"

    if out_path.exists() and not force:
        if verbose:
            print(f"cached: {out_path.name}")
        return out_path

    if verbose:
        print(f"  analysing {video.name}", flush=True)

    fps = probe_fps(video)
    duration = probe_duration(video)
    chunks = run_auto_editor(video, exe, margin, threshold)
    segments = apply_safety_rules(
        chunks_to_segments(chunks, fps, duration), min_gap, min_clip
    )

    kept = sum(e - s for s, e in segments)
    payload = {
        "source": str(video),
        "fps": round(fps, 6),
        "source_duration_s": round(duration, 3),
        "params": {
            "margin": margin,
            "threshold": threshold,
            "min_gap_s": min_gap,
            "min_clip_s": min_clip,
        },
        "kept_duration_s": round(kept, 3),
        "removed_s": round(duration - kept, 3),
        "removed_pct": round((duration - kept) / duration * 100, 1) if duration else 0.0,
        "segments": [
            {"start": round(s, 3), "end": round(e, 3), "duration": round(e - s, 3)}
            for s, e in segments
        ],
    }
    out_path.write_text(json.dumps(payload, indent=2))

    if verbose:
        print(
            f"  {video.stem}: {len(segments)} segment(s), "
            f"{kept:.1f}s of {duration:.1f}s kept "
            f"({payload['removed_pct']}% dead space removed)"
        )
        if not segments:
            print("    warning: nothing survived — threshold or min-clip is too aggressive")

    return out_path


def build_draft_edl(autocut_paths: list[Path], edl_path: Path) -> None:
    """Turn per-source autocut results into an EDL that render.py accepts.

    This is a *draft*, not a finished cut: ranges stay in per-source
    chronological order and every beat is tagged AUTO. Reordering by beat,
    dropping weak takes and choosing a grade are still the editor's job.
    """
    sources: dict[str, str] = {}
    ranges: list[dict] = []
    total = 0.0

    for path in autocut_paths:
        data = json.loads(path.read_text())
        name = Path(data["source"]).stem
        sources[name] = data["source"]
        for seg in data["segments"]:
            ranges.append({
                "source": name,
                "start": seg["start"],
                "end": seg["end"],
                "beat": "AUTO",
                "quote": "",
                "reason": "auto-editor: dead space removed, take not yet chosen",
            })
            total += seg["duration"]

    edl_path.parent.mkdir(parents=True, exist_ok=True)
    edl_path.write_text(json.dumps({
        "version": 1,
        "sources": sources,
        "ranges": ranges,
        "grade": "auto",
        "overlays": [],
        "total_duration_s": round(total, 3),
    }, indent=2))
    print(f"draft EDL: {edl_path} ({len(ranges)} range(s), {total:.1f}s)")


def collect_videos(target: Path) -> list[Path]:
    if target.is_dir():
        return sorted(
            p for p in target.iterdir() if p.is_file() and p.suffix in VIDEO_EXTS
        )
    return [target]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Detect dead space with auto-editor and emit keep-ranges"
    )
    ap.add_argument("target", type=Path, help="Video file or directory of videos")
    ap.add_argument(
        "--edit-dir",
        type=Path,
        default=None,
        help="Edit output directory (default: <video_parent>/edit)",
    )
    ap.add_argument(
        "--margin",
        type=str,
        default="0.05s,0.08s",
        help="Cut padding as START,STOP (default: 0.05s,0.08s — Hard Rule 7 window)",
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Loudness threshold 0-1. Lower keeps quieter speech. Omit for auto-editor's default.",
    )
    ap.add_argument(
        "--min-gap",
        type=float,
        default=0.15,
        help="Silences shorter than this stay in — cutting them is unsafe (default: 0.15s)",
    )
    ap.add_argument(
        "--min-clip",
        type=float,
        default=0.4,
        help="Drop kept segments shorter than this — breaths, not speech (default: 0.4s)",
    )
    ap.add_argument(
        "--edl",
        type=Path,
        default=None,
        help="Also write a draft EDL to this path, ready for render.py",
    )
    ap.add_argument("--force", action="store_true", help="Re-analyse even if cached")
    args = ap.parse_args()

    target = args.target.resolve()
    if not target.exists():
        sys.exit(f"not found: {target}")

    videos = collect_videos(target)
    if not videos:
        sys.exit(f"no video files found in {target}")

    base = target if target.is_dir() else target.parent
    edit_dir = (args.edit_dir or (base / "edit")).resolve()
    exe = require_auto_editor()

    print(f"autocut: {len(videos)} source(s) → {edit_dir / 'autocut'}/")

    # One unreadable take must not cost the analysis of the other nine, so
    # failures are collected and reported at the end instead of raising.
    results: list[Path] = []
    failures: list[tuple[Path, str]] = []
    for v in videos:
        try:
            results.append(analyze_one(
                video=v,
                edit_dir=edit_dir,
                exe=exe,
                margin=args.margin,
                threshold=args.threshold,
                min_gap=args.min_gap,
                min_clip=args.min_clip,
                force=args.force,
            ))
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            print(f"  FAILED {v.name}: {exc}")
            failures.append((v, str(exc)))

    if args.edl:
        edl_path = args.edl if args.edl.is_absolute() else (edit_dir / args.edl)
        build_draft_edl(results, edl_path)

    if failures:
        sys.exit(f"{len(failures)} of {len(videos)} source(s) failed")


if __name__ == "__main__":
    main()
