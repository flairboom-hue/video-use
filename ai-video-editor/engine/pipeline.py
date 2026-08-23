"""Stage orchestration — the thing that turns a file into a finished video.

Two design rules run through this module:

  * A stage whose dependency is missing reports `unavailable` with a fix, and
    the pipeline continues with what it can still do. It never fabricates a
    result to keep the progress bar moving.
  * Every aspect ratio is composited from the BASE cut with overlays and
    captions regenerated at that size. Cropping a finished 16:9 master into
    9:16 slices the graphics in half — which is exactly what the first version
    of this did, and it looked broken.
"""

from __future__ import annotations

import shutil
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import captions as cap
from . import graphics as gfx
from . import media, render, rough_cut, scenes as scene_mod, suggestions as sug
from . import transcribe as tr
from .capabilities import detect, quality_profile
from .project import Clip, Overlay, Project

Progress = Callable[[str, str, str], None]   # stage, status, detail


def _noop(stage: str, status: str, detail: str = "") -> None:
    pass


# --------------------------------------------------------------- analysis ---

def run_analysis(project: Project, on_progress: Progress = _noop) -> None:
    """Import -> probe -> proxy -> scenes -> transcript -> rough cut -> suggestions."""
    caps = detect()
    profile = quality_profile()
    source = Path(project.data["source"])
    settings = project.data["settings"]

    def stage(name: str, status: str, detail: str = "", hint: str = "") -> None:
        project.set_stage(name, status, detail, hint)
        on_progress(name, status, detail)

    # -- probe -------------------------------------------------------------
    stage("import", "running")
    try:
        info = media.probe(source)
    except media.MediaError as exc:
        stage("import", "failed", str(exc),
              "Try re-exporting the file, or check that it is really a video.")
        return
    project.data["media"] = info.to_dict()
    project.save()
    if not info.has_video:
        stage("import", "failed", "no video stream in the file", "")
        return
    stage("import", "done",
          f"{info.width}x{info.height} @ {info.fps:.2f}fps, {info.duration:.1f}s"
          + (", HDR" if info.is_hdr else "")
          + ("" if info.has_audio else ", NO AUDIO"))

    # -- proxy -------------------------------------------------------------
    stage("proxy", "running")
    try:
        proxy = media.build_proxy(source, project.root / "cache" / "proxy.mp4",
                                  height=profile["proxy_height"])
        project.data["proxy"] = str(proxy)
        project.save()
        stage("proxy", "done", f"{profile['proxy_height']}p preview copy")
    except media.MediaError as exc:
        stage("proxy", "failed", str(exc), "Preview will fall back to the source file.")

    # -- scenes ------------------------------------------------------------
    # On the proxy, not the source: scene detection compares downscaled frames
    # anyway, and decoding 1080p for it costs minutes on a long take for no
    # gain in accuracy. Measured on a 10-minute 1080p file: 54s -> ~8s.
    analysis_source = Path(project.data.get("proxy") or source)
    stage("scenes", "running")
    try:
        found = scene_mod.detect_scenes(analysis_source)
        project.data["scenes"] = [s.to_dict() for s in found]
        project.save()
        stage("scenes", "done", f"{len(found)} scene(s)")
    except scene_mod.SceneDetectionUnavailable as exc:
        stage("scenes", "unavailable", "scene detection skipped", str(exc))
    except Exception as exc:
        stage("scenes", "failed", str(exc)[:200], "")

    # -- transcript --------------------------------------------------------
    stage("transcript", "running")
    transcript: tr.Transcript | None = None
    tpath = project.root / "transcripts" / f"{source.stem}.json"
    try:
        transcript = tr.transcribe(
            source, tpath, model=profile["whisper_model"],
            language=settings.get("language") or None,
            device=profile["device"], compute_type=profile["compute_type"],
            batch_size=profile["batch_size"])
        tr.write_srt(transcript, project.root / "transcripts" / "transcript.srt")
        tr.write_vtt(transcript, project.root / "transcripts" / "transcript.vtt")
        stage("transcript", "done", f"{len(transcript.words)} words, "
                                    f"language {transcript.language or 'auto'}")
    except tr.TranscriptionUnavailable as exc:
        stage("transcript", "unavailable",
              "no transcript — filler/repetition removal and captions are off",
              str(exc))
    except Exception as exc:
        stage("transcript", "failed", str(exc)[:200],
              "Check the model download and available memory.")

    # -- rough cut ---------------------------------------------------------
    stage("rough_cut", "running")
    try:
        cut = rough_cut.build(
            source, transcript, info.duration,
            language=settings.get("language", "de"),
            use_silence=settings.get("use_silence", True) and caps.has("auto-editor"),
            remove_fillers=settings.get("remove_fillers", True),
            remove_repetitions=settings.get("remove_repetitions", True),
            remove_false_starts=settings.get("remove_false_starts", True),
        )
        project.data["rough_cut"] = cut.stats()
        project.data["rough_cut"]["removals"] = [r.to_dict() for r in cut.removals]
        project.set_clips([Clip(source=source.stem, start=a, end=b, beat="AUTO")
                           for a, b in cut.keep])
        s = cut.stats()
        detail = (f"{s['removed_pct']}% removed "
                  f"({s['source_duration']:.0f}s -> {s['kept_duration']:.0f}s)")
        if not caps.has("auto-editor"):
            detail += " — auto-editor missing, silence pass skipped"
        stage("rough_cut", "done", detail)
    except Exception as exc:
        project.set_clips([Clip(source=source.stem, start=0.0, end=info.duration)])
        stage("rough_cut", "failed", str(exc)[:200], "Falling back to the full clip.")

    # -- suggestions -------------------------------------------------------
    stage("suggestions", "running")
    if transcript and transcript.words:
        # A flat cap starves a 40-minute talk and floods a 2-minute one.
        # Roughly one proposal per 90 seconds, held between 6 and 40.
        budget = max(6, min(40, int(info.duration / 90) + 4))
        found = sug.detect(transcript, max_suggestions=budget)
        library = Path(project.data.get("assets_dir", "")) if project.data.get("assets_dir") else None
        payload = []
        for s in found:
            d = s.to_dict()
            if s.kind == "broll" and library:
                d["matches"] = sug.match_broll(s, library)
            payload.append(d)
        project.set_suggestions(payload)
        stage("suggestions", "waiting_for_user" if payload else "done",
              f"{len(payload)} proposal(s) need a decision" if payload
              else "nothing worth a graphic found")
    else:
        project.set_suggestions([])
        stage("suggestions", "unavailable", "needs a transcript",
              "Install WhisperX to get creative suggestions.")

    project.snapshot("analysis complete")


# --------------------------------------------------------------- graphics ---

def build_graphic(project: Project, suggestion_id: str, kind: str = "",
                  params: dict | None = None) -> Overlay:
    """Render one accepted suggestion into an overlay clip.

    Anchored to the spoken word, never a timestamp, so the graphic keeps
    landing on its sentence when the cut changes.
    """
    s = next((x for x in project.data["suggestions"] if x["id"] == suggestion_id), None)
    if s is None:
        raise KeyError(f"unknown suggestion: {suggestion_id}")

    params = params or {}
    kind = kind or s.get("graphic_kind") or "number_animation"
    if kind not in gfx.GENERATORS:
        raise ValueError(f"'{kind}' is not implemented. Available: {gfx.available_kinds()}")

    info = project.data.get("media", {})
    # Captions are only burned in when there is a transcript; without one the
    # graphic may use the whole frame.
    source_stem = Path(project.data["source"]).stem
    has_captions = (project.root / "transcripts" / f"{source_stem}.json").exists()
    theme = project.data["settings"].get("graphic_theme", "light_card")
    style = gfx.make_style(
        theme,
        width=int(info.get("width") or 1920),
        height=int(info.get("height") or 1080),
        fps=int(round(float(info.get("fps") or 30))),
        reserve_caption_band=has_captions)

    out = project.root / "graphics" / f"{suggestion_id}_{kind}.mov"
    values = [float(v.replace(",", ".")) for v in s.get("payload", {}).get("values", [])
              if v.replace(",", ".").replace(".", "").isdigit()]
    suffix = "%" if s.get("payload", {}).get("percent") else params.get("suffix", "")

    if kind == "number_animation":
        gfx.number_animation(out, params.get("value", values[0] if values else 0),
                             params.get("label", ""), suffix, style)
    elif kind == "bar_chart":
        gfx.bar_chart(out, params.get("values", values or [1]),
                      params.get("labels"), style, suffix=suffix)
    elif kind == "comparison":
        pair = params.get("values", values)
        gfx.comparison(out, pair[0] if pair else 0, pair[1] if len(pair) > 1 else 0,
                       params.get("label_before", "VORHER"),
                       params.get("label_after", "NACHHER"), suffix, style)
    elif kind == "lower_third":
        gfx.lower_third(out, params.get("title", s.get("quote", "")[:40]),
                        params.get("subtitle", ""), style)
    elif kind == "text_animation":
        gfx.text_animation(out, params.get("text", s.get("quote", ""))[:60], style)
    elif kind == "pie_chart":
        gfx.pie_chart(out, params.get("values", values or [1]),
                      params.get("labels"), style)
    elif kind == "icon_row":
        gfx.icon_row(out, params.get("items") or
                     [("check", w) for w in s.get("quote", "").split()[:4]], style)

    duration = media.probe(out).duration
    overlay = Overlay(file=str(out), duration=duration,
                      anchor_word=s["anchor_word"],
                      anchor_occurrence=s.get("anchor_occurrence", 1),
                      reveal_duration=params.get("reveal_duration", 0.4),
                      suggestion_id=suggestion_id)
    project.remove_overlay(suggestion_id)      # replacing, not stacking
    project.add_overlay(overlay)
    project.update_suggestion(suggestion_id, status="accepted", graphic_kind=kind)
    return overlay


# ---------------------------------------------------------------- render ---

@dataclass
class RenderResult:
    path: Path
    aspect: str
    duration: float


def _resolve_anchors(project: Project, transcript: tr.Transcript | None,
                     clips: list[tuple[float, float]]) -> list[dict]:
    """Anchor words -> output-timeline positions, against the CURRENT cut."""
    overlays = [dict(o) for o in project.data["timeline"]["overlays"]]
    if not overlays:
        return []
    if not transcript:
        return [o for o in overlays if o.get("start_in_output") is not None]

    words = cap.words_on_output_timeline(transcript, clips)
    index = [(rough_cut.normalize(w.text), w) for w in words]

    resolved = []
    for o in overlays:
        anchor = o.get("anchor_word")
        if not anchor:
            if o.get("start_in_output") is not None:
                resolved.append(o)
            continue
        needle = rough_cut.normalize(anchor)
        hits = [w for token, w in index if token == needle]
        occ = int(o.get("anchor_occurrence", 1))
        if not hits:
            continue                    # the line was cut — drop, do not misplace
        hit = hits[min(occ, len(hits)) - 1]
        o["start_in_output"] = max(0.0, hit.start - float(o.get("reveal_duration", 0.0)))
        resolved.append(o)
    return resolved


def render_video(project: Project, aspect: str = "16:9", preview: bool = False,
                 out_path: Path | None = None,
                 on_progress: Progress = _noop) -> RenderResult:
    """Composite the current project state at one aspect ratio."""
    source = Path(project.data["source"])
    clips = [(c.start, c.end) for c in project.clips]
    if not clips:
        raise render.RenderError("the cut is empty — nothing to render")

    profile = quality_profile()
    width, height = render.ASPECTS.get(aspect, render.ASPECTS["16:9"])
    spec = render.RenderSpec(width=width, height=height,
                             fps=int(round(float(project.data["media"].get("fps") or 30))),
                             encoder="libx264")
    if preview:
        spec.crf, spec.preset = 26, "veryfast"
        spec.width, spec.height = width // 2, height // 2

    work = project.root / "cache" / f"render_{aspect.replace(':', 'x')}"
    work.mkdir(parents=True, exist_ok=True)

    on_progress("render", "running", "extracting segments")
    # Video fills the frame (crop); overlays are fitted with padding below.
    segs = render.extract_segments(source, clips, work, spec,
                                   grade=project.data["settings"].get("grade", "auto"),
                                   fit="cover")
    base = render.concat(segs, work / "base.mp4", work)

    transcript = None
    tpath = project.root / "transcripts" / f"{source.stem}.json"
    if tpath.exists():
        transcript = tr.load(tpath)

    # Overlays are regenerated per aspect rather than cropped from the master.
    on_progress("render", "running", "compositing overlays")
    overlays = _resolve_anchors(project, transcript, clips)
    scaled = _scale_overlays(overlays, work, spec)

    ass = None
    if transcript and transcript.words:
        on_progress("render", "running", "burning captions")
        ass = cap.build_for_project(
            transcript, clips,
            project.data["settings"].get("caption_style", "bold_center"),
            work / "captions.ass", width=spec.width, height=spec.height)

    comp = render.composite(base, scaled, ass, work / "composited.mp4", work, spec)
    on_progress("render", "running", "normalising loudness")
    final = out_path or (work / "final.mp4")
    final.parent.mkdir(parents=True, exist_ok=True)
    render.normalize_loudness(comp, final)

    duration = media.probe(final).duration
    on_progress("render", "done", f"{aspect} · {duration:.1f}s")
    return RenderResult(path=final, aspect=aspect, duration=duration)


def _scale_overlays(overlays: list[dict], work: Path, spec: render.RenderSpec) -> list[dict]:
    """Fit each overlay to the target frame, preserving its aspect.

    Scaling with padding keeps a 16:9 chart intact inside a 9:16 frame instead
    of cropping half of it away.
    """
    out = []
    for i, o in enumerate(overlays):
        src = Path(o["file"])
        if not src.exists():
            continue
        # Key the cache on the source identity, not the position. Keying by
        # index silently reuses a previous graphic when a suggestion is
        # re-rendered as a different kind — the overlay changes on disk and the
        # render keeps showing the old one.
        stamp = f"{src.stem}_{int(src.stat().st_mtime)}_{spec.width}x{spec.height}"
        dest = work / f"ov_{stamp}.mov"
        if not dest.exists():
            subprocess_run = render._run
            subprocess_run([
                "ffmpeg", "-y", "-i", str(src),
                "-vf", (f"scale={spec.width}:{spec.height}:force_original_aspect_ratio=decrease,"
                        f"pad={spec.width}:{spec.height}:(ow-iw)/2:(oh-ih)/2:color=#00000000"),
                "-c:v", "qtrle", "-pix_fmt", "argb", str(dest)])
        scaled = dict(o)
        scaled["file"] = str(dest)
        out.append(scaled)
    return out
