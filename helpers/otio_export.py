"""Convert a video-use EDL into an OpenTimelineIO timeline.

The handoff path out of this skill. `render.py` bakes an EDL into pixels; this
writes the same EDL as an editable timeline an NLE can open, so the agent's cut
becomes a starting point for hand-finishing instead of something to redo.

    edl.json ──> render.py    ──> final.mp4        (finished, flat)
             └─> otio_export.py ──> timeline.xml   (editable, relinkable)

Adapters (the useful ones):
    otio_json   .otio  native, lossless, keeps beat/quote/reason metadata
    fcp_xml     .xml   FCP7 XML — imported by Premiere Pro and DaVinci Resolve
    cmx_3600    .edl   classic CMX EDL — universal, cuts only
    AAF         .aaf   Avid

What survives the trip: the cut points, source media links, per-clip beat
markers, and (except in cmx_3600, which is single-track) the overlay track.
What does not: colour grades (an ffmpeg filter chain has no NLE equivalent),
audio fades, and burned subtitles. Those are `render.py`'s job and are listed
as warnings at export time rather than silently dropped.

Frame rate: an NLE timeline has ONE rate. Sources shot at different rates are
conformed to a single timeline rate — the first source's, unless --fps says
otherwise — which is what an NLE would do on import anyway. A mismatch is
reported so it is a decision rather than a surprise.

Usage:
    python helpers/otio_export.py <edl.json> -o timeline.otio
    python helpers/otio_export.py <edl.json> -o timeline.xml --adapter fcp_xml
    python helpers/otio_export.py <edl.json> -o cut.edl --adapter cmx_3600
    python helpers/otio_export.py <edl.json> -o timeline.xml --fps 25
    python helpers/otio_export.py <edl.json> -o timeline.otio --no-overlays
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

try:
    import opentimelineio as otio
except ImportError:
    sys.exit(
        "opentimelineio not installed.\n"
        "Install it with:  pip install OpenTimelineIO-Plugins\n"
        "(the -Plugins package adds the fcp_xml / cmx_3600 / AAF adapters;\n"
        " plain `pip install opentimelineio` only writes .otio)"
    )


# Adapter name → conventional extension, for the "did you mean" hint on a
# mismatch. Not a whitelist: otio.adapters is the authority on what exists.
# Adapters that reject a multi-track timeline outright. The overlay track is
# dropped for these rather than letting the write raise.
SINGLE_TRACK_ADAPTERS = {"cmx_3600"}

ADAPTER_EXTENSIONS = {
    "otio_json": ".otio",
    "fcp_xml": ".xml",
    "cmx_3600": ".edl",
    "AAF": ".aaf",
}


def probe_fps(video: Path) -> float:
    """Average frame rate of the first video stream."""
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
    raise RuntimeError(f"no usable frame rate on {video.name} — is there a video stream?")


def probe_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def resolve_path(maybe_path: str, base: Path) -> Path:
    """Resolve a path that may be absolute or relative to `base`.

    Same convention as render.py: EDL paths are relative to the edit dir.
    """
    p = Path(maybe_path)
    return p if p.is_absolute() else (base / p).resolve()


def time_range(start_s: float, duration_s: float, fps: float) -> otio.opentime.TimeRange:
    return otio.opentime.TimeRange(
        start_time=otio.opentime.RationalTime(round(start_s * fps), fps),
        duration=otio.opentime.RationalTime(round(duration_s * fps), fps),
    )


def external_reference(
    media: Path, fps: float, available_duration_s: float | None
) -> otio.schema.ExternalReference:
    """Media link with an available_range so the NLE knows the full source.

    Without available_range an NLE can import the clip but cannot trim beyond
    the cut — which defeats the point of handing over an editable timeline.
    """
    available_range = None
    if available_duration_s is not None:
        available_range = time_range(0.0, available_duration_s, fps)
    return otio.schema.ExternalReference(
        target_url=media.resolve().as_uri(),
        available_range=available_range,
    )


def build_cut_track(
    edl: dict,
    edit_dir: Path,
    fps: float,
    media_info: dict[str, tuple[Path, float]],
) -> otio.schema.Track:
    """V1: the EDL ranges, back to back, in EDL order."""
    track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)

    for i, r in enumerate(edl["ranges"]):
        src_name = r["source"]
        media, source_duration = media_info[src_name]
        start, end = float(r["start"]), float(r["end"])
        beat = r.get("beat") or ""

        clip = otio.schema.Clip(
            name=f"{src_name}_{i:02d}" + (f"_{beat}" if beat else ""),
            media_reference=external_reference(media, fps, source_duration),
            source_range=time_range(start, end - start, fps),
        )
        # The editorial reasoning is the part a human finisher most needs and
        # the part every non-native adapter drops. Keep it in metadata (which
        # .otio preserves in full) and mirror the beat as a marker, which the
        # NLE adapters do carry.
        clip.metadata["video_use"] = {
            "beat": beat,
            "quote": r.get("quote", ""),
            "reason": r.get("reason", ""),
            "source_start_s": start,
            "source_end_s": end,
        }
        if beat:
            clip.markers.append(otio.schema.Marker(
                name=beat,
                marked_range=time_range(start, 0.0, fps),
                color=otio.schema.MarkerColor.GREEN,
            ))
        track.append(clip)

    return track


def build_overlay_track(
    overlays: list[dict], edit_dir: Path, fps: float
) -> otio.schema.Track | None:
    """V2: rendered animation clips, positioned by start_in_output.

    Overlays are sorted and gap-filled. Two overlays that overlap in time
    cannot share one track, so the later one is dropped with a warning rather
    than silently shifting the timeline.
    """
    placed = sorted(overlays, key=lambda o: float(o.get("start_in_output", 0.0)))
    track = otio.schema.Track(name="V2", kind=otio.schema.TrackKind.Video)
    playhead = 0.0

    for ov in placed:
        start = float(ov.get("start_in_output", 0.0))
        media = resolve_path(ov["file"], edit_dir)

        if start < playhead - 1e-6:
            print(f"  warning: overlay {media.name} at {start:.2f}s overlaps the "
                  f"previous one (ends {playhead:.2f}s) — not exported")
            continue

        # An absent duration means "read it off the media"; an explicit 0 is a
        # malformed overlay. `or` would conflate the two and probe for both.
        declared = ov.get("duration")
        if declared is not None:
            duration = float(declared)
        elif media.exists():
            duration = probe_duration(media)
        else:
            duration = 0.0

        if not media.exists():
            print(f"  warning: overlay media missing, link will be broken: {media}")

        if duration <= 0:
            print(f"  warning: overlay {media.name} has no duration — not exported")
            continue

        if start > playhead + 1e-6:
            track.append(otio.schema.Gap(source_range=time_range(0.0, start - playhead, fps)))

        track.append(otio.schema.Clip(
            name=media.stem,
            media_reference=external_reference(
                media, fps, duration if media.exists() else None
            ),
            source_range=time_range(0.0, duration, fps),
        ))
        playhead = start + duration

    return track if any(isinstance(c, otio.schema.Clip) for c in track) else None


def report_lost_in_translation(edl: dict, adapter: str) -> None:
    """Say out loud what the target format cannot carry."""
    notes: list[str] = []
    if edl.get("grade"):
        notes.append(
            f"grade '{edl['grade']}' is an ffmpeg filter chain with no NLE "
            "equivalent — regrade in the NLE, or use render.py for the graded cut"
        )
    if edl.get("subtitles"):
        notes.append(
            f"subtitles ({edl['subtitles']}) are not part of the timeline — "
            "import the .srt into the NLE separately"
        )
    notes.append("30ms audio fades are applied by render.py, not carried here")
    if adapter != "otio_json":
        notes.append(
            "the per-clip quote/reason metadata survives in .otio only — export "
            "an .otio alongside if the reasoning needs to travel with the cut"
        )
    if adapter == "cmx_3600":
        notes.append(
            "cmx_3600 carries cuts, clip names and markers (as * LOC lines) only — "
            "the overlay track and the quote/reason metadata are dropped"
        )

    print("\nnot carried into the export:")
    for n in notes:
        print(f"  - {n}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Convert a video-use EDL into an OpenTimelineIO timeline"
    )
    ap.add_argument("edl", type=Path, help="Path to edl.json")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output timeline path")
    ap.add_argument(
        "--adapter",
        type=str,
        default=None,
        help="OTIO adapter (default: inferred from the output extension). "
             f"Common: {', '.join(ADAPTER_EXTENSIONS)}",
    )
    ap.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Timeline frame rate (default: the first source's rate)",
    )
    ap.add_argument(
        "--name", type=str, default=None, help="Timeline name (default: the EDL's stem)"
    )
    ap.add_argument(
        "--no-overlays", action="store_true", help="Export the cut track only"
    )
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    if not edl_path.exists():
        sys.exit(f"EDL not found: {edl_path}")
    edl = json.loads(edl_path.read_text())
    edit_dir = edl_path.parent

    if not edl.get("ranges"):
        sys.exit("EDL has no ranges — nothing to export")

    # -- media + frame rate ---------------------------------------------------
    # Every source is probed once; a missing one is fatal here (unlike a missing
    # overlay) because its rate and duration define the timeline.
    media_info: dict[str, tuple[Path, float]] = {}
    rates: dict[str, float] = {}
    for name, raw in edl["sources"].items():
        media = resolve_path(raw, edit_dir)
        if not media.exists():
            sys.exit(f"source media not found: {media}")
        rates[name] = probe_fps(media)
        media_info[name] = (media, probe_duration(media))

    used = [r["source"] for r in edl["ranges"]]
    missing = sorted(set(used) - set(media_info))
    if missing:
        sys.exit(f"EDL ranges reference unknown source(s): {', '.join(missing)}")

    fps = args.fps or rates[used[0]]
    distinct = sorted({round(v, 3) for v in rates.values()})
    if len(distinct) > 1:
        print(f"note: sources have mixed frame rates {distinct}; "
              f"conforming the timeline to {fps:g} fps")

    # -- adapter (resolved before the build: it decides what can be built) ----
    out_path = args.output if args.output.is_absolute() else (edit_dir / args.output)

    adapter = args.adapter
    if adapter is None:
        suffix = out_path.suffix.lower()
        adapter = next(
            (a for a, ext in ADAPTER_EXTENSIONS.items() if ext == suffix), None
        )
        if adapter is None:
            sys.exit(
                f"cannot infer an adapter from '{out_path.suffix}'. "
                f"Pass --adapter explicitly (available: "
                f"{', '.join(sorted(otio.adapters.available_adapter_names()))})"
            )

    available = otio.adapters.available_adapter_names()
    if adapter not in available:
        sys.exit(
            f"adapter '{adapter}' is not installed. Available: {', '.join(sorted(available))}\n"
            "The NLE adapters ship in OpenTimelineIO-Plugins:  pip install OpenTimelineIO-Plugins"
        )

    # -- build ----------------------------------------------------------------
    timeline = otio.schema.Timeline(name=args.name or edl_path.stem)
    timeline.global_start_time = otio.opentime.RationalTime(0, fps)
    timeline.tracks.append(build_cut_track(edl, edit_dir, fps, media_info))

    overlays = [] if args.no_overlays else edl.get("overlays") or []
    if overlays and adapter in SINGLE_TRACK_ADAPTERS:
        print(f"note: {adapter} supports one video track only — "
              f"{len(overlays)} overlay(s) not exported")
        overlays = []
    if overlays:
        overlay_track = build_overlay_track(overlays, edit_dir, fps)
        if overlay_track is not None:
            timeline.tracks.append(overlay_track)

    # -- write ----------------------------------------------------------------
    out_path.parent.mkdir(parents=True, exist_ok=True)
    otio.adapters.write_to_file(timeline, str(out_path), adapter_name=adapter)

    n_clips = len(timeline.tracks[0])
    duration = timeline.duration().to_seconds()
    print(f"wrote {out_path} via {adapter}")
    print(f"  {len(timeline.tracks)} track(s), {n_clips} clip(s), {duration:.2f}s")
    report_lost_in_translation(edl, adapter)


if __name__ == "__main__":
    main()
