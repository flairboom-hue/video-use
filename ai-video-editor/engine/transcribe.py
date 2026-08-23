"""Word-level transcription.

Reuses the WhisperX helper that already ships in this repo (helpers/) rather
than reimplementing the format conversion — that converter is covered by the
test suite and the two must not drift apart.

Word-level timing is non-negotiable for this pipeline. Phrase-level subtitles
lose the sub-second gap data that the rough cut, the caption animation and the
overlay anchoring all read.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

# helpers/ lives next to the app, not inside it.
HELPERS = Path(__file__).resolve().parent.parent.parent / "helpers"
if HELPERS.is_dir() and str(HELPERS) not in sys.path:
    sys.path.insert(0, str(HELPERS))


class TranscriptionUnavailable(RuntimeError):
    """WhisperX is not installed. Carries the fix, not just the failure."""


@dataclass
class Word:
    text: str
    start: float
    end: float
    speaker: str | None = None


@dataclass
class Transcript:
    words: list[Word]
    language: str = ""
    engine: str = ""

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def duration(self) -> float:
        return self.words[-1].end if self.words else 0.0

    def to_scribe_dict(self) -> dict:
        """The flat shape helpers/render.py and pack_transcripts.py consume."""
        out: list[dict] = []
        prev_end = None
        for w in self.words:
            # Gaps are explicit entries, not implied by the next word's start:
            # pack_transcripts.py breaks phrases on them.
            if prev_end is not None and w.start - prev_end >= 0.02:
                out.append({"type": "spacing", "text": " ",
                            "start": round(prev_end, 3),
                            "end": round(w.start, 3)})
            entry = {"type": "word", "text": w.text,
                     "start": round(w.start, 3), "end": round(w.end, 3)}
            if w.speaker:
                entry["speaker_id"] = w.speaker
            out.append(entry)
            prev_end = w.end
        return {"_engine": self.engine, "language_code": self.language,
                "text": self.text, "words": out}


def from_scribe_dict(data: dict) -> Transcript:
    words = [
        Word(text=w.get("text", ""), start=float(w.get("start", 0.0)),
             end=float(w.get("end", 0.0)), speaker=w.get("speaker_id"))
        for w in data.get("words", [])
        if w.get("type") == "word" and w.get("start") is not None
    ]
    return Transcript(words=words, language=data.get("language_code") or "",
                      engine=data.get("_engine") or "scribe")


def load(path: Path) -> Transcript:
    return from_scribe_dict(json.loads(Path(path).read_text()))


def transcribe(video: Path, out_path: Path, model: str = "large-v3",
               language: str | None = None, device: str = "auto",
               compute_type: str | None = None, batch_size: int = 16,
               diarize: bool = False, force: bool = False) -> Transcript:
    """Transcribe to <out_path>. Cached unless force=True.

    Raises TranscriptionUnavailable with an actionable message when WhisperX is
    missing, so the pipeline can mark the stage `unavailable` instead of
    pretending it produced an empty transcript.
    """
    out_path = Path(out_path)
    if out_path.exists() and not force:
        return load(out_path)

    try:
        import transcribe_whisperx as tw  # from helpers/
    except ImportError as exc:
        raise TranscriptionUnavailable(
            "The WhisperX helper could not be imported. Expected it at "
            f"{HELPERS / 'transcribe_whisperx.py'}"
        ) from exc

    try:
        import whisperx  # noqa: F401
    except ImportError as exc:
        raise TranscriptionUnavailable(
            "WhisperX is not installed, so no transcript can be produced.\n"
            "Fix: pip install whisperx  (large download; a CUDA GPU makes it "
            "roughly an order of magnitude faster, but CPU works)"
        ) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tw.transcribe_one(
        video=Path(video),
        edit_dir=out_path.parent.parent,   # helper writes <edit>/transcripts/<stem>.json
        model_name=model, language=language, device=device,
        compute_type=compute_type, batch_size=batch_size,
        diarize=diarize, force=force, verbose=True,
    )
    return load(out_path)


def write_srt(transcript: Transcript, path: Path, max_words: int = 2) -> Path:
    """Plain SRT export. The animated caption track is built separately."""
    def stamp(t: float) -> str:
        h, rem = divmod(max(0.0, t), 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)):03d}"

    lines: list[str] = []
    for i in range(0, len(transcript.words), max_words):
        chunk = transcript.words[i:i + max_words]
        lines += [str(i // max_words + 1),
                  f"{stamp(chunk[0].start)} --> {stamp(chunk[-1].end)}",
                  " ".join(w.text for w in chunk), ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_vtt(transcript: Transcript, path: Path, max_words: int = 2) -> Path:
    def stamp(t: float) -> str:
        h, rem = divmod(max(0.0, t), 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"

    lines = ["WEBVTT", ""]
    for i in range(0, len(transcript.words), max_words):
        chunk = transcript.words[i:i + max_words]
        lines += [f"{stamp(chunk[0].start)} --> {stamp(chunk[-1].end)}",
                  " ".join(w.text for w in chunk), ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
