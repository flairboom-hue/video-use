"""The project file is the reason nothing is destructive."""
from __future__ import annotations

import json

import pytest

from engine.project import Clip, Overlay, Project


@pytest.fixture
def project(tmp_path):
    src = tmp_path / "take.mp4"
    src.write_bytes(b"x")
    return Project.create(tmp_path / "projects", src)


class TestNonDestructive:
    def test_the_source_is_recorded_but_never_written(self, project, tmp_path):
        src = Path_of(project)
        before = src.read_bytes()
        project.set_clips([Clip("take", 1.0, 2.0)])
        project.snapshot("cut")
        assert src.read_bytes() == before

    def test_edits_live_only_in_the_project_file(self, project):
        project.set_clips([Clip("take", 1.0, 2.0)])
        stored = json.loads(project.path.read_text())
        assert stored["timeline"]["clips"][0]["start"] == 1.0


class TestVersioning:
    def test_snapshot_then_restore_returns_the_earlier_cut(self, project):
        project.set_clips([Clip("take", 0.0, 10.0)])
        v1 = project.snapshot("full")
        project.set_clips([Clip("take", 0.0, 2.0)])
        project.snapshot("trimmed")
        assert project.duration == pytest.approx(2.0)
        project.restore(v1)
        assert project.duration == pytest.approx(10.0)

    def test_restoring_is_itself_recorded(self, project):
        project.set_clips([Clip("take", 0.0, 10.0)])
        v1 = project.snapshot("full")
        project.snapshot("later")
        project.restore(v1)
        assert any("restored" in h["label"] for h in project.data["history"])

    def test_restoring_a_missing_version_fails_loudly(self, project):
        with pytest.raises(FileNotFoundError):
            project.restore(99)


class TestOverlays:
    def test_accepting_the_same_suggestion_twice_replaces_it(self, project):
        project.add_overlay(Overlay(file="a.mov", duration=1.0, suggestion_id="s1"))
        project.remove_overlay("s1")
        project.add_overlay(Overlay(file="b.mov", duration=1.0, suggestion_id="s1"))
        files = [o["file"] for o in project.data["timeline"]["overlays"]]
        assert files == ["b.mov"]


class TestEdl:
    def test_edl_shape_matches_what_the_renderer_reads(self, project):
        project.set_clips([Clip("take", 1.0, 3.0), Clip("take", 5.0, 6.0)])
        edl = project.to_edl()
        assert edl["version"] == 1
        assert len(edl["ranges"]) == 2
        assert edl["total_duration_s"] == pytest.approx(3.0)
        assert set(edl["ranges"][0]) >= {"source", "start", "end", "beat"}


def Path_of(project):
    from pathlib import Path
    return Path(project.data["source"])
