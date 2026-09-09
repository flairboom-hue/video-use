#!/usr/bin/env python3
"""Word-level transcription without PyTorch.

Same output as `transcribe_whisperx.py` — the flat Scribe `words` list the rest
of this skill reads — produced by faster-whisper instead. It exists because
WhisperX is a heavy install that fails in ordinary places: it drags in torch,
pyannote and omegaconf, and on a Debian-based image the vendored setuptools
breaks the build of a transitive dependency before any of it downloads.

What you give up against WhisperX:

  - Forced alignment. WhisperX re-aligns Whisper's word times against a
    phoneme model; faster-whisper reports the times Whisper itself produced.
    Both are good enough to cut on and to caption with; WhisperX's are tighter
    at word boundaries.
  - Speaker diarization. Not offered here at all rather than half-offered —
    with one speaker it buys nothing, and pretending otherwise would put an
    empty `speaker_id` on every word.

What you get: an install that takes seconds, no CUDA question, and CPU speed
that is roughly comparable because CTranslate2 is quantised.

    python helpers/transcribe_fasterwhisper.py <video_path>
    python helpers/transcribe_fasterwhisper.py <videos_dir> --language de
    python helpers/transcribe_fasterwhisper.py <video> --model medium
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transcribe_whisperx import (  # noqa: E402
    collect_videos, extract_audio, whisperx_to_scribe,
)

ENGINE = "faster-whisper"


def pick_compute(device: str) -> tuple[str, str]:
    """Resolve (device, compute_type).

    int8 on CPU is not a quality compromise worth agonising over — it is the
    difference between usable and not. float16 needs CUDA.
    """
    if device == "auto":
        try:
            import ctranslate2  # noqa: PLC0415
            device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
        except Exception:
            device = "cpu"
    return device, ("float16" if device == "cuda" else "int8")


def segments_to_result(segments, language: str | None) -> dict:
    """faster-whisper objects -> the dict shape whisperx_to_scribe expects.

    Adapting here rather than writing a second converter: the Scribe format has
    details that took a while to get right (gaps as explicit spacing entries,
    undated words kept rather than dropped) and they should exist once.
    """
    out = []
    for seg in segments:
        words = []
        for w in (seg.words or []):
            words.append({"word": w.word, "start": w.start, "end": w.end})
        out.append({"words": words, "text": seg.text})
    return {"segments": out, "language": language}


def transcribe_one(video: Path, edit_dir: Path, model_name: str = "medium",
                   language: str | None = None, device: str = "auto",
                   compute_type: str | None = None, force: bool = False,
                   verbose: bool = True, **_ignored) -> Path:
    """Transcribe one file into <edit_dir>/transcripts/<stem>.json.

    Signature mirrors the WhisperX helper so the two are interchangeable; the
    arguments that only mean something there (batch_size, diarize) are accepted
    and ignored rather than raising, because the caller should not have to know
    which engine it got.
    """
    from faster_whisper import WhisperModel  # noqa: PLC0415 - heavy, load late

    video = Path(video)
    dest = Path(edit_dir) / "transcripts" / f"{video.stem}.json"
    if dest.exists() and not force:
        if verbose:
            print(f"  {video.name}: transcript exists, skipping")
        return dest

    dev, compute = pick_compute(device)
    compute = compute_type or compute
    if verbose:
        print(f"  {video.name}: {model_name} on {dev} ({compute})")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        extract_audio(video, wav)
        model = WhisperModel(model_name, device=dev, compute_type=compute)
        segments, info = model.transcribe(
            str(wav), language=language, word_timestamps=True)
        # `segments` is a generator; the model runs as it is consumed.
        payload = whisperx_to_scribe(
            segments_to_result(list(segments), info.language),
            language=info.language, engine=ENGINE)

    payload["_model"] = model_name
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    if verbose:
        spoken = sum(1 for w in payload["words"] if w["type"] == "word")
        print(f"  {video.name}: {spoken} words, language {payload['language_code']}"
              f" -> {dest}")
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path, help="video file or directory")
    ap.add_argument("--edit-dir", type=Path, default=None,
                    help="where transcripts/ is written (default: alongside)")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--language", default=None, help="e.g. de; omit to detect")
    ap.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    ap.add_argument("--compute-type", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    videos = collect_videos(args.target)
    if not videos:
        print(f"No video files found at {args.target}")
        raise SystemExit(1)

    edit_dir = args.edit_dir or (args.target if args.target.is_dir()
                                 else args.target.parent)
    print(f"{len(videos)} file(s) -> {edit_dir}/transcripts/")
    failed = 0
    for video in videos:
        try:
            transcribe_one(video, edit_dir, model_name=args.model,
                           language=args.language, device=args.device,
                           compute_type=args.compute_type, force=args.force)
        except Exception as exc:                      # one bad file, not the batch
            failed += 1
            print(f"  {video.name}: FAILED — {exc}")
    if failed:
        print(f"\n{failed} of {len(videos)} failed.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
