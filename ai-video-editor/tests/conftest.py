"""Shared fixtures. The suite is pure logic — no ffmpeg, no models, no network."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from engine.transcribe import Transcript, Word  # noqa: E402


@pytest.fixture
def make_transcript():
    def _make(sentences: list[tuple[str, float]], word_len: float = 0.32,
              step: float = 0.36) -> Transcript:
        words: list[Word] = []
        for text, start in sentences:
            t = start
            for token in text.split():
                words.append(Word(token, t, t + word_len))
                t += step
        return Transcript(words=words, language="de")
    return _make
