"""The project file — the single source of truth, and the reason nothing is destructive.

Every decision the pipeline or the user makes lands here as data. The source
video is opened read-only and never rewritten; rendering reads this file and
produces a NEW file. Undo is therefore free: restore an older version of the
JSON and re-render.

Versioning is copy-on-write. Each `snapshot()` freezes the current state under
projects/<id>/versions/vNNN.json, so "go back to version 3" is a file copy
rather than an inverse-operation replay that can drift.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass
class Clip:
    """One kept range of the source, in source seconds."""
    source: str
    start: float
    end: float
    beat: str = ""
    note: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Overlay:
    """A rendered graphic, anchored to a spoken word rather than a timestamp.

    `start_in_output` is filled in at render time from the anchor, so an
    overlay keeps landing on its sentence after the cut changes.
    """
    file: str
    duration: float
    anchor_word: str = ""
    anchor_occurrence: int = 1
    reveal_duration: float = 0.0
    start_in_output: float | None = None
    suggestion_id: str = ""


@dataclass
class Stage:
    name: str
    status: str = "pending"   # pending|running|done|skipped|unavailable|failed|waiting_for_user
    detail: str = ""
    hint: str = ""            # how to fix it, when unavailable/failed
    updated_at: float = 0.0


class Project:
    def __init__(self, root: Path, data: dict):
        self.root = Path(root)
        self.data = data

    # ------------------------------------------------------------ lifecycle ---

    @classmethod
    def create(cls, projects_dir: Path, source: Path, name: str = "") -> "Project":
        pid = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
        root = Path(projects_dir) / pid
        (root / "versions").mkdir(parents=True, exist_ok=True)
        (root / "transcripts").mkdir(exist_ok=True)
        (root / "graphics").mkdir(exist_ok=True)
        (root / "cache").mkdir(exist_ok=True)

        data = {
            "schema": SCHEMA_VERSION,
            "id": pid,
            "name": name or Path(source).stem,
            "created_at": time.time(),
            "source": str(Path(source).resolve()),   # read-only, never written to
            "media": {},
            "stages": {},
            "timeline": {"clips": [], "overlays": [], "captions": None,
                         "broll": [], "music": []},
            "rough_cut": {},
            "scenes": [],
            "suggestions": [],
            "settings": {
                "language": "de",
                "caption_style": "bold_center",
                "graphic_theme": "light_card",
                "aspect": "16:9",
                "remove_fillers": True,
                "remove_repetitions": True,
                "remove_false_starts": True,
                "use_silence": True,
            },
            "version": 0,
            "history": [],
        }
        p = cls(root, data)
        p.save()
        return p

    @classmethod
    def load(cls, root: Path) -> "Project":
        root = Path(root)
        return cls(root, json.loads((root / "project.json").read_text()))

    @property
    def path(self) -> Path:
        return self.root / "project.json"

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a crash mid-write must not leave a truncated project.
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))
        tmp.replace(self.path)

    def snapshot(self, label: str) -> int:
        self.data["version"] += 1
        v = self.data["version"]
        self.data["history"].append(
            {"version": v, "label": label, "at": time.time()})
        self.save()
        shutil.copy2(self.path, self.root / "versions" / f"v{v:03d}.json")
        return v

    def restore(self, version: int) -> None:
        src = self.root / "versions" / f"v{version:03d}.json"
        if not src.exists():
            raise FileNotFoundError(f"version {version} does not exist")
        data = json.loads(src.read_text())
        # Keep the history so restoring is itself an auditable step.
        data["history"] = self.data["history"] + [
            {"version": data["version"], "label": f"restored v{version}", "at": time.time()}]
        self.data = data
        self.save()

    # --------------------------------------------------------------- stages ---

    def set_stage(self, name: str, status: str, detail: str = "", hint: str = "") -> None:
        self.data["stages"][name] = asdict(
            Stage(name=name, status=status, detail=detail, hint=hint, updated_at=time.time()))
        self.save()

    def stage(self, name: str) -> dict:
        return self.data["stages"].get(name, asdict(Stage(name=name)))

    # ------------------------------------------------------------- timeline ---

    def set_clips(self, clips: list[Clip]) -> None:
        self.data["timeline"]["clips"] = [asdict(c) for c in clips]
        self.save()

    @property
    def clips(self) -> list[Clip]:
        return [Clip(**c) for c in self.data["timeline"]["clips"]]

    @property
    def duration(self) -> float:
        return sum(c.duration for c in self.clips)

    def add_overlay(self, overlay: Overlay) -> None:
        self.data["timeline"]["overlays"].append(asdict(overlay))
        self.save()

    def remove_overlay(self, suggestion_id: str) -> bool:
        before = len(self.data["timeline"]["overlays"])
        self.data["timeline"]["overlays"] = [
            o for o in self.data["timeline"]["overlays"]
            if o.get("suggestion_id") != suggestion_id]
        self.save()
        return len(self.data["timeline"]["overlays"]) < before

    # ---------------------------------------------------------- suggestions ---

    def set_suggestions(self, suggestions: list[dict]) -> None:
        self.data["suggestions"] = suggestions
        self.save()

    def update_suggestion(self, sid: str, **changes: Any) -> dict | None:
        for s in self.data["suggestions"]:
            if s["id"] == sid:
                s.update(changes)
                self.save()
                return s
        return None

    def pending_questions(self) -> list[dict]:
        return [s for s in self.data["suggestions"] if s.get("status") == "pending"]

    # ------------------------------------------------------------- exports ---

    def to_edl(self) -> dict:
        """The EDL shape helpers/render.py consumes, so the proven renderer runs."""
        source = self.data["source"]
        name = Path(source).stem
        return {
            "version": 1,
            "sources": {name: source},
            "ranges": [
                {"source": name, "start": c.start, "end": c.end,
                 "beat": c.beat or "AUTO", "quote": "", "reason": c.note}
                for c in self.clips
            ],
            "grade": self.data["settings"].get("grade", "auto"),
            "overlays": [
                {k: v for k, v in o.items() if v is not None and k != "suggestion_id"}
                for o in self.data["timeline"]["overlays"]
            ],
            "total_duration_s": round(self.duration, 3),
        }

    def summary(self) -> dict:
        rc = self.data.get("rough_cut", {})
        return {
            "id": self.data["id"],
            "name": self.data["name"],
            "source": self.data["source"],
            "media": self.data.get("media", {}),
            "version": self.data["version"],
            "duration": round(self.duration, 2),
            "clips": len(self.data["timeline"]["clips"]),
            "overlays": len(self.data["timeline"]["overlays"]),
            "scenes": len(self.data.get("scenes", [])),
            "stages": self.data["stages"],
            "rough_cut": rc,
            "open_questions": len(self.pending_questions()),
            "settings": self.data["settings"],
        }
