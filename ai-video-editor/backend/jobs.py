"""A single background worker with an explicit status machine.

Deliberately not Celery or RQ: this is a local single-user app, and a broker
would be one more thing to install and one more thing to fail. One worker
thread with a queue covers it, and a failed job never takes the server down —
it records the traceback and the next job proceeds.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, asdict, field
from typing import Any, Callable

STATUSES = ("queued", "processing", "waiting_for_user", "completed", "failed")


@dataclass
class Job:
    id: str
    kind: str
    project_id: str = ""
    status: str = "queued"
    detail: str = ""
    error: str = ""
    hint: str = ""
    progress: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    result: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class JobQueue:
    def __init__(self, on_event: Callable[[dict], None] | None = None):
        self._q: queue.Queue[tuple[Job, Callable]] = queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._on_event = on_event or (lambda e: None)
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, kind: str, fn: Callable[[Job], Any], project_id: str = "") -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, project_id=project_id)
        with self._lock:
            self._jobs[job.id] = job
        self._emit(job)
        self._q.put((job, fn))
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self, project_id: str = "") -> list[dict]:
        with self._lock:
            jobs = list(self._jobs.values())
        if project_id:
            jobs = [j for j in jobs if j.project_id == project_id]
        return [j.to_dict() for j in sorted(jobs, key=lambda j: j.created_at, reverse=True)]

    def note(self, job: Job, stage: str, status: str, detail: str = "") -> None:
        job.progress.append({"stage": stage, "status": status,
                             "detail": detail, "at": time.time()})
        job.detail = f"{stage}: {detail}" if detail else stage
        self._emit(job)

    def _emit(self, job: Job) -> None:
        try:
            self._on_event({"type": "job", "job": job.to_dict()})
        except Exception:
            pass

    def _run(self) -> None:
        while True:
            job, fn = self._q.get()
            job.status = "processing"
            self._emit(job)
            try:
                result = fn(job)
                if job.status == "processing":
                    job.status = "completed"
                job.result = result if isinstance(result, dict) else {}
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)[:500]
                job.hint = getattr(exc, "hint", "") or _hint_for(exc)
                job.result = {"traceback": traceback.format_exc()[-1500:]}
            finally:
                job.finished_at = time.time()
                self._emit(job)
                self._q.task_done()


def _hint_for(exc: Exception) -> str:
    """Turn the common failures into something the user can act on."""
    text = str(exc).lower()
    if "ffmpeg" in text and "not found" in text:
        return "Install ffmpeg and make sure it is on PATH."
    if "cuda" in text or "out of memory" in text:
        return "Not enough GPU memory. Switch to CPU mode or use a smaller model."
    if "whisperx" in text:
        return "Install WhisperX: pip install whisperx"
    return ""
