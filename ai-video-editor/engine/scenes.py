"""Scene detection via PySceneDetect.

Two uses in this pipeline: telling the editor where the visuals actually
change, and indexing the B-roll library so a suggestion can point at a real
clip instead of a filename.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Scene:
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = round(self.duration, 3)
        return d


class SceneDetectionUnavailable(RuntimeError):
    pass


def detect_scenes(video: Path, threshold: float = 27.0, min_scene_len: float = 1.0,
                  downscale: int | None = None) -> list[Scene]:
    """Adaptive content detection. Returns [] for a single-shot video.

    `min_scene_len` is in seconds here rather than frames, because every other
    module in this engine speaks seconds and converting at the boundary keeps
    the rest honest.
    """
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import ContentDetector
    except ImportError as exc:
        raise SceneDetectionUnavailable(
            "scenedetect is not installed. Fix: pip install 'scenedetect[opencv]'"
        ) from exc

    video_stream = open_video(str(video))
    fps = video_stream.frame_rate or 30.0

    manager = SceneManager()
    if downscale:
        manager.auto_downscale = False
        manager.downscale = downscale
    manager.add_detector(
        ContentDetector(threshold=threshold, min_scene_len=int(min_scene_len * fps))
    )
    manager.detect_scenes(video_stream, show_progress=False)

    scenes = []
    for i, (start, end) in enumerate(manager.get_scene_list()):
        scenes.append(Scene(index=i, start=start.get_seconds(), end=end.get_seconds()))
    return scenes
