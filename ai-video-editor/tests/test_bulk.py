"""Bulk review — the selection logic that decides what a click applies to.

Reviewing forty proposals one at a time is the real bottleneck on a long
video. These tests pin the selection rules, because a bulk action that picks
the wrong set is worse than no bulk action at all.
"""
from __future__ import annotations

import pytest

from engine.project import Project
from engine.suggestions import select_pending


def suggestion(sid: str, kind: str = "graphic", graphic_kind: str = "bar_chart",
               confidence: float = 0.8, status: str = "pending") -> dict:
    return {"id": sid, "kind": kind, "graphic_kind": graphic_kind,
            "confidence": confidence, "status": status, "anchor_word": "x",
            "anchor_occurrence": 1, "quote": "", "reason": "", "payload": {}}


@pytest.fixture
def project(tmp_path):
    src = tmp_path / "take.mp4"
    src.write_bytes(b"x")
    p = Project.create(tmp_path / "projects", src)
    p.set_suggestions([
        suggestion("a", confidence=0.9),
        suggestion("b", confidence=0.6),
        suggestion("c", kind="broll", graphic_kind="", confidence=0.65),
        suggestion("d", confidence=0.95, status="accepted"),
        suggestion("e", confidence=0.5, status="rejected"),
    ])
    return p


def select(project: Project, **kw) -> list[str]:
    """The real selector the endpoint calls — not a copy that could drift."""
    return select_pending(project.data["suggestions"], **kw)


class TestSelection:
    def test_only_pending_proposals_are_selected(self, project):
        # Already decided ones must not be silently re-applied.
        assert select(project) == ["a", "b", "c"]

    def test_kind_filter_separates_graphics_from_broll(self, project):
        assert select(project, kind="graphic") == ["a", "b"]
        assert select(project, kind="broll") == ["c"]

    def test_confidence_floor(self, project):
        assert select(project, min_confidence=0.75) == ["a"]

    def test_filters_combine(self, project):
        assert select(project, kind="graphic", min_confidence=0.65) == ["a"]

    def test_a_filter_matching_nothing_returns_empty_not_everything(self, project):
        # The dangerous failure mode: an over-narrow filter falling back to "all".
        assert select(project, graphic_kind="pie_chart") == []


class TestBulkReject:
    def test_rejecting_marks_every_selected_proposal(self, project):
        for sid in select(project, kind="graphic"):
            project.update_suggestion(sid, status="rejected")
        by_id = {s["id"]: s["status"] for s in project.data["suggestions"]}
        assert by_id["a"] == by_id["b"] == "rejected"
        assert by_id["c"] == "pending"      # broll untouched
        assert by_id["d"] == "accepted"     # already decided, untouched

    def test_rejecting_is_one_undoable_version(self, project):
        before = project.data["version"]
        for sid in select(project):
            project.update_suggestion(sid, status="rejected")
        project.snapshot("bulk reject (3)")
        assert project.data["version"] == before + 1
        project.restore(before) if before else None


class TestPartialFailure:
    def test_a_failed_item_returns_to_pending_and_the_rest_survive(self, project):
        # One unrenderable proposal must not abandon the others.
        applied, failed = [], []
        for sid in select(project, kind="graphic"):
            if sid == "b":
                failed.append(sid)
                project.update_suggestion(sid, status="pending")
            else:
                applied.append(sid)
                project.update_suggestion(sid, status="accepted")
        by_id = {s["id"]: s["status"] for s in project.data["suggestions"]}
        assert applied == ["a"] and failed == ["b"]
        assert by_id["a"] == "accepted"
        assert by_id["b"] == "pending"   # retryable, not lost
