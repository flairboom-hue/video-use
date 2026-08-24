"""FastAPI app: REST + WebSocket + the static frontend.

Everything is local. No upload leaves the machine; the "upload" endpoint
copies the file into INPUT/ and opens it read-only from there.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import captions as cap                     # noqa: E402
from engine import graphics as gfx                     # noqa: E402
from engine import llm, pipeline, qc                   # noqa: E402
from engine import suggestions as sug                  # noqa: E402
from engine.capabilities import detect, quality_profile  # noqa: E402
from engine.project import Project                     # noqa: E402
from engine.render import ASPECTS                      # noqa: E402
from backend.jobs import JobQueue                      # noqa: E402
from backend.watcher import InputWatcher               # noqa: E402

INPUT = ROOT / "INPUT"
OUTPUT = ROOT / "OUTPUT"
PROJECTS = ROOT / "projects"
ASSETS = ROOT / "ASSETS"
DB = ROOT / "config" / "app.db"

for d in (INPUT, OUTPUT, PROJECTS, ASSETS, DB.parent):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI Video Editor", version="0.1.0")

# ------------------------------------------------------------------- state ---

_sockets: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


def broadcast(event: dict) -> None:
    """Called from the worker thread — hop onto the event loop safely."""
    if _loop is None:
        return
    asyncio.run_coroutine_threadsafe(_broadcast(event), _loop)


async def _broadcast(event: dict) -> None:
    dead = []
    for ws in list(_sockets):
        try:
            await ws.send_text(json.dumps(event))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _sockets.discard(ws)


jobs = JobQueue(on_event=broadcast)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY, name TEXT, source TEXT, root TEXT, created_at REAL)""")
    conn.commit()
    return conn


def register(project: Project) -> None:
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO projects VALUES (?,?,?,?,?)",
                     (project.data["id"], project.data["name"], project.data["source"],
                      str(project.root), project.data["created_at"]))


def load_project(pid: str) -> Project:
    root = PROJECTS / pid
    if not (root / "project.json").exists():
        raise HTTPException(404, f"project {pid} not found")
    return Project.load(root)


# --------------------------------------------------------------- lifecycle ---

@app.on_event("startup")
async def _startup() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    watcher = InputWatcher(INPUT, on_new=lambda p: _import(p, autostart=True))
    watcher.start()
    app.state.watcher = watcher


def _import(source: Path, autostart: bool = True) -> Project:
    project = Project.create(PROJECTS, source)
    project.data["assets_dir"] = str(ASSETS / "broll")
    project.save()
    register(project)
    broadcast({"type": "project_created", "project": project.summary()})
    if autostart:
        _start_analysis(project)
    return project


def _start_analysis(project: Project):
    def work(job):
        def progress(stage, status, detail=""):
            jobs.note(job, stage, status, detail)
            broadcast({"type": "stage", "project_id": project.data["id"],
                       "stage": stage, "status": status, "detail": detail})
        pipeline.run_analysis(project, on_progress=progress)
        summary = project.summary()
        if summary["open_questions"]:
            job.status = "waiting_for_user"
        broadcast({"type": "project_updated", "project": summary})
        return {"project": summary}
    return jobs.submit("analysis", work, project.data["id"])


# ------------------------------------------------------------------ routes ---

@app.get("/api/health")
def health() -> dict:
    caps = detect()
    return {
        "ok": not caps.missing_required(),
        "capabilities": caps.to_dict(),
        "profile": quality_profile(),
        "missing_required": [t.name for t in caps.missing_required()],
        "llm": {"provider": llm.configured().name, "available": llm.available()},
        "caption_styles": cap.available_styles(),
        "graphic_kinds": gfx.available_kinds(),
        "graphic_themes": gfx.available_themes(),
        "motion_blur_levels": gfx.available_motion_blur(),
        "icons": gfx.available_icons(),
        "aspects": list(ASPECTS),
    }


@app.post("/api/projects")
async def upload(file: UploadFile = File(...)) -> dict:
    dest = INPUT / Path(file.filename).name
    if dest.exists():
        dest = INPUT / f"{dest.stem}_{int(time.time())}{dest.suffix}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    # The watcher would also catch it; mark it handled so it is not imported twice.
    app.state.watcher._imported.add(str(dest))
    project = _import(dest)
    return {"project": project.summary()}


@app.get("/api/projects")
def list_projects() -> dict:
    out = []
    for root in sorted(PROJECTS.glob("*/project.json"), reverse=True):
        try:
            out.append(Project.load(root.parent).summary())
        except Exception:
            continue
    return {"projects": out}


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    p = load_project(pid)
    return {"project": p.summary(),
            "suggestions": p.data["suggestions"],
            "timeline": p.data["timeline"],
            "scenes": p.data["scenes"],
            "rough_cut": p.data.get("rough_cut", {}),
            "history": p.data["history"]}


@app.post("/api/projects/{pid}/analyze")
def reanalyze(pid: str) -> dict:
    job = _start_analysis(load_project(pid))
    return {"job": job.to_dict()}


@app.get("/api/projects/{pid}/transcript")
def transcript(pid: str) -> dict:
    p = load_project(pid)
    src = Path(p.data["source"]).stem
    f = p.root / "transcripts" / f"{src}.json"
    if not f.exists():
        raise HTTPException(404, "no transcript — WhisperX may not be installed")
    return json.loads(f.read_text())


# -- suggestions -----------------------------------------------------------

@app.post("/api/projects/{pid}/suggestions/{sid}/accept")
def accept(pid: str, sid: str, body: dict | None = None) -> dict:
    project = load_project(pid)
    body = body or {}

    def work(job):
        jobs.note(job, "graphic", "running", sid)
        overlay = pipeline.build_graphic(project, sid, body.get("kind", ""),
                                         body.get("params", {}))
        project.snapshot(f"accepted {sid}")
        broadcast({"type": "project_updated", "project": project.summary()})
        return {"overlay": overlay.__dict__}

    return {"job": jobs.submit("graphic", work, pid).to_dict()}


@app.post("/api/projects/{pid}/suggestions/bulk")
def bulk_suggestions(pid: str, body: dict) -> dict:
    """Accept, reject or defer many proposals in one call.

    Reviewing forty proposals one click at a time is the actual bottleneck on a
    long video, and it is a decision the user is qualified to make in bulk:
    "graphics yes, B-roll no" is a normal editorial stance.

    Selection is by explicit ids, or by filter (kind / graphic_kind / minimum
    confidence). Bulk ACCEPT still renders each graphic, so it runs as one job
    with per-item progress rather than a blocking request; a single failure is
    recorded and the rest continue.
    """
    project = load_project(pid)
    action = (body or {}).get("action", "")
    if action not in {"accept", "reject", "defer"}:
        raise HTTPException(400, "action must be accept, reject or defer")

    ids = body.get("ids")
    if ids is None:
        ids = sug.select_pending(
            project.data["suggestions"],
            kind=body.get("kind"),
            graphic_kind=body.get("graphic_kind"),
            min_confidence=float(body.get("min_confidence", 0.0)))

    known = {s["id"] for s in project.data["suggestions"]}
    unknown = [i for i in ids if i not in known]
    ids = [i for i in ids if i in known]
    if not ids:
        return {"applied": [], "failed": [], "unknown": unknown,
                "message": "nothing matched the selection"}

    if action in {"reject", "defer"}:
        status = "rejected" if action == "reject" else "deferred"
        for sid in ids:
            if action == "reject":
                project.remove_overlay(sid)
            project.update_suggestion(sid, status=status)
        project.snapshot(f"bulk {action} ({len(ids)})")
        broadcast({"type": "project_updated", "project": project.summary()})
        return {"applied": ids, "failed": [], "unknown": unknown,
                "message": f"{len(ids)} proposal(s) {status}"}

    def work(job):
        applied, failed = [], []
        for n, sid in enumerate(ids, start=1):
            jobs.note(job, "graphic", "running", f"{n}/{len(ids)} · {sid}")
            try:
                pipeline.build_graphic(project, sid)
                applied.append(sid)
            except Exception as exc:
                # One bad proposal must not abandon the other thirty-nine.
                failed.append({"id": sid, "error": str(exc)[:200]})
                project.update_suggestion(sid, status="pending")
        project.snapshot(f"bulk accept ({len(applied)})")
        broadcast({"type": "project_updated", "project": project.summary()})
        if failed and not applied:
            job.status = "failed"
            job.error = f"all {len(failed)} graphic(s) failed"
        return {"applied": applied, "failed": failed, "unknown": unknown}

    return {"job": jobs.submit("graphic_bulk", work, pid).to_dict(),
            "queued": len(ids), "unknown": unknown}


@app.post("/api/projects/{pid}/suggestions/{sid}/reject")
def reject(pid: str, sid: str) -> dict:
    p = load_project(pid)
    p.remove_overlay(sid)
    updated = p.update_suggestion(sid, status="rejected")
    if updated is None:
        raise HTTPException(404, "unknown suggestion")
    broadcast({"type": "project_updated", "project": p.summary()})
    return {"suggestion": updated}


@app.post("/api/projects/{pid}/suggestions/{sid}/defer")
def defer(pid: str, sid: str) -> dict:
    p = load_project(pid)
    return {"suggestion": p.update_suggestion(sid, status="deferred")}


# -- render / preview / export --------------------------------------------

@app.post("/api/projects/{pid}/preview")
def preview(pid: str, body: dict | None = None) -> dict:
    project = load_project(pid)
    aspect = (body or {}).get("aspect", project.data["settings"].get("aspect", "16:9"))

    def work(job):
        def progress(stage, status, detail=""):
            jobs.note(job, stage, status, detail)
            broadcast({"type": "stage", "project_id": pid,
                       "stage": stage, "status": status, "detail": detail})
        out = project.root / "cache" / f"preview_{aspect.replace(':', 'x')}.mp4"
        result = pipeline.render_video(project, aspect=aspect, preview=True,
                                       out_path=out, on_progress=progress)
        broadcast({"type": "preview_ready", "project_id": pid,
                   "url": f"/api/projects/{pid}/media/preview_{aspect.replace(':', 'x')}.mp4"})
        return {"path": str(result.path), "duration": result.duration}

    return {"job": jobs.submit("preview", work, pid).to_dict()}


@app.post("/api/projects/{pid}/export")
def export(pid: str, body: dict | None = None) -> dict:
    project = load_project(pid)
    body = body or {}
    targets = body.get("targets") or ["youtube"]
    force = bool(body.get("force"))

    presets = {
        "youtube": ("16:9", "YouTube"),
        "shorts":  ("9:16", "Shorts"),
        "reels":   ("9:16", "Reels"),
        "tiktok":  ("9:16", "TikTok"),
        "square":  ("1:1",  "Square"),
    }

    def work(job):
        results, blocked = [], []
        for key in targets:
            if key not in presets:
                continue
            aspect, folder = presets[key]
            jobs.note(job, "render", "running", f"{folder} ({aspect})")

            def progress(stage, status, detail=""):
                jobs.note(job, stage, status, detail)
                broadcast({"type": "stage", "project_id": pid,
                           "stage": stage, "status": status, "detail": detail})

            dest_dir = OUTPUT / folder
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{project.data['name']}.mp4"
            r = pipeline.render_video(project, aspect=aspect, preview=False,
                                      out_path=dest, on_progress=progress)

            jobs.note(job, "qc", "running", folder)
            w, h = ASPECTS[aspect]
            findings = qc.check(dest, expect_duration=project.duration, expect_size=(w, h))
            v = qc.verdict(findings)
            if not v["can_export"] and not force:
                blocked.append({"target": key, "verdict": v})
                dest.unlink(missing_ok=True)      # never ship a file QC rejected
                jobs.note(job, "qc", "failed", f"{folder}: {v['blocking'][0]['message']}")
                continue
            results.append({"target": key, "path": str(dest),
                            "duration": r.duration, "qc": v})
            jobs.note(job, "qc", "done", folder)

        # Sidecars are cheap and always useful.
        srt = project.root / "transcripts" / "transcript.srt"
        if srt.exists():
            (OUTPUT / "Captions").mkdir(parents=True, exist_ok=True)
            shutil.copy2(srt, OUTPUT / "Captions" / f"{project.data['name']}.srt")
        (OUTPUT / "Project").mkdir(parents=True, exist_ok=True)
        shutil.copy2(project.path, OUTPUT / "Project" / f"{project.data['name']}.json")

        if blocked:
            job.status = "failed"
            job.error = "quality control blocked one or more exports"
            job.hint = "Fix the findings, or repeat with force=true to override."
        return {"exported": results, "blocked": blocked}

    return {"job": jobs.submit("export", work, pid).to_dict()}


@app.get("/api/projects/{pid}/qc")
def run_qc(pid: str) -> dict:
    p = load_project(pid)
    candidate = p.root / "cache" / "render_16x9" / "final.mp4"
    if not candidate.exists():
        raise HTTPException(404, "render a preview first")
    return qc.verdict(qc.check(candidate, expect_duration=p.duration))


# -- versions --------------------------------------------------------------

@app.post("/api/projects/{pid}/restore/{version}")
def restore(pid: str, version: int) -> dict:
    p = load_project(pid)
    try:
        p.restore(version)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    broadcast({"type": "project_updated", "project": p.summary()})
    return {"project": p.summary()}


# -- chat ------------------------------------------------------------------

@app.post("/api/projects/{pid}/chat")
def chat(pid: str, body: dict) -> dict:
    project = load_project(pid)
    text = (body or {}).get("message", "")
    cmd = llm.parse_command(text)

    if cmd is None:
        if llm.available():
            try:
                answer = llm.complete(
                    f"Project: {json.dumps(project.summary())[:1500]}\n\nUser: {text}",
                    system=("You are a video editing assistant. Answer briefly. "
                            "If the user asks for an edit you cannot express as one of "
                            f"{[c[0] for c in llm.COMMANDS]}, say so plainly."))
                return {"reply": answer, "applied": None}
            except llm.Unavailable as exc:
                return {"reply": str(exc), "applied": None}
        return {"reply": ("I did not recognise that as an edit. Try e.g. "
                          "\"entferne die ersten 5 Sekunden\", \"mach die Captions größer\", "
                          "\"entferne alle Grafiken\", \"9:16\"."),
                "applied": None}

    applied = _apply_command(project, cmd)
    project.snapshot(f"chat: {cmd['command']}")
    broadcast({"type": "project_updated", "project": project.summary()})
    return {"reply": applied["message"], "applied": cmd, "project": project.summary()}


def _apply_command(project: Project, cmd: dict) -> dict:
    name, arg = cmd["command"], cmd["arg"]
    clips = project.clips

    if name == "trim_start" and clips:
        amount = float(arg)
        remaining = amount
        kept = []
        for c in clips:
            if remaining <= 0:
                kept.append(c)
                continue
            if c.duration <= remaining:
                remaining -= c.duration
                continue
            c.start += remaining
            remaining = 0
            kept.append(c)
        project.set_clips(kept)
        return {"message": f"Removed the first {amount:g}s. New length: {project.duration:.1f}s."}

    if name == "trim_end" and clips:
        amount = float(arg)
        remaining = amount
        kept = []
        for c in reversed(clips):
            if remaining <= 0:
                kept.insert(0, c)
                continue
            if c.duration <= remaining:
                remaining -= c.duration
                continue
            c.end -= remaining
            remaining = 0
            kept.insert(0, c)
        project.set_clips(kept)
        return {"message": f"Removed the last {amount:g}s. New length: {project.duration:.1f}s."}

    if name == "caption_size":
        style_key = project.data["settings"].get("caption_style", "bold_center")
        style = cap.STYLES.get(style_key)
        delta = 4 if arg in {"größer", "bigger"} else -4
        if style:
            style.size = max(8, style.size + delta)
        return {"message": f"Caption size is now {style.size if style else '?'}."}

    if name == "caption_style":
        project.data["settings"]["caption_style"] = arg
        project.save()
        return {"message": f"Caption style set to {arg}."}

    if name == "remove_overlays":
        n = len(project.data["timeline"]["overlays"])
        project.data["timeline"]["overlays"] = []
        for s in project.data["suggestions"]:
            if s.get("status") == "accepted":
                s["status"] = "rejected"
        project.save()
        return {"message": f"Removed {n} overlay(s)."}

    if name == "aspect":
        project.data["settings"]["aspect"] = arg
        project.save()
        return {"message": f"Target aspect is now {arg}. Render a preview to see it."}

    if name == "theme":
        project.data["settings"]["graphic_theme"] = arg
        project.save()
        return {"message": f"Graphic theme set to {arg}. Re-render accepted "
                           "graphics to apply it."}

    if name == "motion_blur":
        arg = {"aus": "off"}.get(arg, arg)      # the German phrasing, normalised
        project.data["settings"]["motion_blur"] = arg
        project.save()
        cost = {"off": "", "light": " (~7x render time)",
                "normal": " (~13x)", "heavy": " (~20x)"}.get(arg, "")
        return {"message": f"Motion blur set to {arg}{cost}. "
                           "Re-render accepted graphics to apply it."}

    if name == "grade":
        project.data["settings"]["grade"] = arg
        project.save()
        return {"message": f"Colour grade set to {arg}."}

    if name == "make_short" and clips:
        target = float(arg)
        kept, total = [], 0.0
        for c in clips:
            if total >= target:
                break
            take = min(c.duration, target - total)
            kept.append(type(c)(source=c.source, start=c.start, end=c.start + take,
                                beat=c.beat, note=c.note))
            total += take
        project.set_clips(kept)
        return {"message": f"Built a {total:.1f}s short from the first clips."}

    return {"message": "Recognised the command but there was nothing to change."}


# -- settings --------------------------------------------------------------

@app.post("/api/projects/{pid}/settings")
def settings(pid: str, body: dict) -> dict:
    p = load_project(pid)
    p.data["settings"].update(body or {})
    p.save()
    return {"settings": p.data["settings"]}


# -- media -----------------------------------------------------------------

@app.get("/api/projects/{pid}/media/{name}")
def media_file(pid: str, name: str):
    p = load_project(pid)
    # Never serve outside the project's cache directory.
    candidate = (p.root / "cache" / name).resolve()
    if not str(candidate).startswith(str((p.root / "cache").resolve())) or not candidate.exists():
        raise HTTPException(404, "not found")
    return FileResponse(candidate, media_type="video/mp4")


@app.get("/api/projects/{pid}/source")
def source_file(pid: str):
    p = load_project(pid)
    proxy = p.data.get("proxy")
    path = Path(proxy) if proxy and Path(proxy).exists() else Path(p.data["source"])
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/jobs")
def list_jobs(project_id: str = "") -> dict:
    return {"jobs": jobs.list(project_id)}


# -- websocket -------------------------------------------------------------

@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    _sockets.add(socket)
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _sockets.discard(socket)


# -- frontend --------------------------------------------------------------

FRONTEND = ROOT / "frontend"


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse((FRONTEND / "index.html").read_text(encoding="utf-8"))


if FRONTEND.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
