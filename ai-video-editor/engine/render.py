"""The compositor.

Order is not negotiable — each of these produces a silent failure if moved:

  1. per-segment extract, with the grade and 30ms audio fades baked in
  2. lossless -c copy concat (a filtergraph here double-encodes every segment)
  3. overlays, PTS-shifted so each animation's frame 0 lands at its window
  4. captions LAST, or overlays cover them
  5. loudness normalisation on the finished mix

Reframing happens after all of it, from the finished 16:9 master, so the
vertical cuts stay in sync with the horizontal one for free.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Social platforms normalise to about -14 LUFS; delivering louder just gets
# turned down, and delivering quieter sounds weak next to everything else.
LOUDNORM_I, LOUDNORM_TP, LOUDNORM_LRA = -14.0, -1.0, 11.0

FADE = 0.03   # 30ms — below this you hear the cut, above it you hear the fade

ASPECTS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1":  (1080, 1080),
    "4:5":  (1080, 1350),
}

TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")

GRADES = {
    "neutral": "eq=contrast=1.03:saturation=0.98",
    "warm_cinematic": "eq=contrast=1.06:saturation=1.05:gamma_r=1.03:gamma_b=0.98",
    "punch": "eq=contrast=1.12:saturation=1.10",
    "flat": "",
}


class RenderError(RuntimeError):
    pass


@dataclass
class RenderSpec:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    crf: int = 20
    preset: str = "medium"
    encoder: str = "libx264"

    @classmethod
    def preview(cls) -> "RenderSpec":
        return cls(width=1280, height=720, crf=26, preset="veryfast")


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg failed:\n{' '.join(cmd[:8])} …\n{proc.stderr[-700:]}")


def _is_hdr(video: Path) -> bool:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=color_transfer",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True)
    return p.stdout.strip() in {"smpte2084", "arib-std-b67"}


def fit_filter(width: int, height: int, mode: str = "cover") -> str:
    """How source pixels meet a target frame.

    "cover"   crops to fill — what a vertical export needs. Letterboxing a
              talking head into 9:16 wastes two thirds of the screen.
    "contain" scales and pads — right for overlays, where losing the edge of a
              chart is worse than showing background around it.
    """
    if mode == "contain":
        return (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}")


def extract_segments(source: Path, clips: list[tuple[float, float]], work: Path,
                     spec: RenderSpec, grade: str = "auto",
                     fit: str = "cover", crop_x: str | None = None) -> list[Path]:
    work.mkdir(parents=True, exist_ok=True)
    chain = GRADES.get(grade, GRADES["neutral"]) if grade != "auto" else GRADES["neutral"]
    hdr = _is_hdr(source)

    out: list[Path] = []
    for i, (start, end) in enumerate(clips):
        dur = end - start
        if dur <= 0:
            continue
        dest = work / f"seg_{i:03d}.mp4"

        vf = []
        if hdr:
            vf.append(TONEMAP)
        if crop_x and fit == "cover":
            # Subject-tracked crop: take the window first, then scale it.
            vf.append(f"crop=w=ih*{spec.width}/{spec.height}:h=ih:x='{crop_x}':y=0")
            vf.append(f"scale={spec.width}:{spec.height}")
        else:
            vf.append(fit_filter(spec.width, spec.height, fit))
        vf.append("setsar=1")
        if chain:
            vf.append(chain)
        if not hdr:
            vf.append("format=yuv420p")

        af = (f"afade=t=in:st=0:d={FADE},"
              f"afade=t=out:st={max(0.0, dur - FADE):.3f}:d={FADE}")

        _run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(source),
              "-t", f"{dur:.3f}",
              "-vf", ",".join(vf), "-af", af,
              "-r", str(spec.fps),
              "-c:v", spec.encoder, "-preset", spec.preset, "-crf", str(spec.crf),
              "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
              str(dest)])
        out.append(dest)
    if not out:
        raise RenderError("no segments to render — the cut is empty")
    return out


def concat(segments: list[Path], dest: Path, work: Path) -> Path:
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in segments))
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
          "-c", "copy", str(dest)])
    return dest


def composite(base: Path, overlays: list[dict], captions: Path | None,
              dest: Path, work: Path, spec: RenderSpec) -> Path:
    """Overlays (PTS-shifted) then captions LAST."""
    if not overlays and not captions:
        shutil.copy2(base, dest)
        return dest

    inputs = ["-i", str(base)]
    for ov in overlays:
        inputs += ["-i", str(ov["file"])]

    steps: list[str] = []
    label = "0:v"
    for idx, ov in enumerate(overlays, start=1):
        t = float(ov.get("start_in_output") or 0.0)
        steps.append(f"[{idx}:v]setpts=PTS-STARTPTS+{t}/TB[ov{idx}]")
        nxt = f"v{idx}"
        steps.append(f"[{label}][ov{idx}]overlay=0:0:enable='between(t,{t},{t + float(ov['duration']):.3f})'[{nxt}]")
        label = nxt

    if captions:
        escaped = str(captions).replace("\\", "/").replace(":", "\\:")
        steps.append(f"[{label}]subtitles='{escaped}'[vout]")
        label = "vout"

    _run(["ffmpeg", "-y", *inputs,
          "-filter_complex", ";".join(steps),
          "-map", f"[{label}]", "-map", "0:a?",
          "-c:v", spec.encoder, "-preset", spec.preset, "-crf", str(spec.crf),
          "-pix_fmt", "yuv420p", "-c:a", "copy", str(dest)])
    return dest


def normalize_loudness(src: Path, dest: Path) -> Path:
    """Two-pass loudnorm. Falls back to a copy if measurement fails."""
    probe = subprocess.run(
        ["ffmpeg", "-i", str(src), "-af",
         f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True)
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", probe.stderr, re.S)
    if not match:
        shutil.copy2(src, dest)
        return dest
    m = json.loads(match.group(0))
    af = (f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}:"
          f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
          f"offset={m.get('target_offset', 0)}:linear=true:print_format=summary")
    _run(["ffmpeg", "-y", "-i", str(src), "-af", af,
          "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(dest)])
    return dest


def reframe(src: Path, dest: Path, aspect: str, spec: RenderSpec,
            track: list[tuple[float, float]] | None = None) -> Path:
    """Convert the finished master to another aspect ratio.

    With a `track` (x-centres over time from engine.reframe) the crop window
    follows the subject; without it the crop is centred. A centred crop on a
    talking head is usually acceptable; on a two-shot it is not, which is why
    the tracked path exists and is reported separately.
    """
    w, h = ASPECTS.get(aspect, ASPECTS["9:16"])
    if track:
        expr = _crop_expression(track)
        vf = (f"crop=w=ih*{w}/{h}:h=ih:x='{expr}':y=0,"
              f"scale={w}:{h},setsar=1,format=yuv420p")
    else:
        vf = (f"crop=w=ih*{w}/{h}:h=ih,scale={w}:{h},setsar=1,format=yuv420p")

    _run(["ffmpeg", "-y", "-i", str(src), "-vf", vf,
          "-c:v", spec.encoder, "-preset", spec.preset, "-crf", str(spec.crf),
          "-c:a", "copy", str(dest)])
    return dest


def _crop_expression(track: list[tuple[float, float]]) -> str:
    """Piecewise-constant x over time, clamped to the frame.

    ffmpeg expressions have no arrays, so the track is compiled into nested
    if() calls. Keep the sample count modest — engine.reframe smooths and
    decimates before handing the track over.
    """
    expr = f"{track[-1][1]:.1f}"
    for t, x in reversed(track[:-1]):
        expr = f"if(lt(t,{t:.2f}),{x:.1f},{expr})"
    return f"clip({expr},0,iw-ow)"
