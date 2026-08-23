"""Shared fixtures.

The helpers are standalone scripts in `helpers/`, not an installed package, so
the suite puts that directory on sys.path rather than restructuring the repo
around the tests.

Everything under test here is pure logic — no ffmpeg, no network, no models.
That is deliberate: these tests defend the rules that produce *silent* failures
(a caption that drifts, an overlay on the wrong sentence, a cut inside a word),
and those are exactly the ones a human reviewing the render might miss.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HELPERS = Path(__file__).resolve().parent.parent / "helpers"
if str(HELPERS) not in sys.path:
    sys.path.insert(0, str(HELPERS))


def word(text: str, start: float, end: float, speaker: str | None = None) -> dict:
    """One Scribe-shaped word entry."""
    w = {"type": "word", "text": text, "start": start, "end": end}
    if speaker:
        w["speaker_id"] = speaker
    return w


def spacing(start: float, end: float) -> dict:
    """A gap entry. pack_transcripts.py breaks phrases on these."""
    return {"type": "spacing", "text": " ", "start": start, "end": end}


@pytest.fixture
def make_transcript(tmp_path):
    """Write a Scribe-shaped transcript into <edit>/transcripts/<name>.json."""
    import json

    def _make(edit_dir: Path, name: str, words: list[dict]) -> Path:
        d = edit_dir / "transcripts"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{name}.json"
        p.write_text(json.dumps({"words": words}))
        return p

    return _make
