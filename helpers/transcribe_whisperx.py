"""Transcribe locally with WhisperX, in the Scribe transcript format.

A drop-in replacement for `transcribe.py` that runs entirely on your machine:
no API key, no upload, no per-minute cost. Writes to the same
<edit_dir>/transcripts/<video_stem>.json path in the same shape, so
`pack_transcripts.py` and `render.py --build-subtitles` consume it unchanged
and the two engines can be mixed inside one project.

Why the format conversion exists: WhisperX returns segments-of-words, while
the rest of this skill reads a flat `words` list where the GAPS are explicit
`spacing` entries. That gap list is not cosmetic — `pack_transcripts.py`
breaks phrases on it, and phrase boundaries are what the editor cuts on. So
the converter reconstructs spacing entries from the silence between
consecutive words rather than dropping the timing information.

Engine choice, in short:
  - Scribe (`transcribe.py`)  — best accuracy, costs money, needs upload.
  - WhisperX (this file)      — free and private, needs a GPU to be quick.

Diarization (--diarize) is optional and needs a HuggingFace token in
HF_TOKEN, plus a one-time acceptance of the pyannote model terms. Without it
you still get word-level timestamps, just no speaker labels.

Cached: if the transcript already exists, the run is skipped (--force to
re-transcribe). A transcript written by Scribe counts as a cache hit — delete
it first if you want to switch engines for that source.

Usage:
    python helpers/transcribe_whisperx.py <video_path>
    python helpers/transcribe_whisperx.py <videos_dir>
    python helpers/transcribe_whisperx.py <videos_dir> --language de
    python helpers/transcribe_whisperx.py <video> --model medium --device cpu
    python helpers/transcribe_whisperx.py <video> --diarize --num-speakers 2
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


VIDEO_EXTS = {".mp4", ".MP4", ".mov", ".MOV", ".mkv", ".MKV", ".avi", ".AVI", ".m4v"}

# pack_transcripts.py breaks a phrase on any spacing entry at or above its own
# threshold (0.5s by default). Emitting spacing for every sub-millisecond gap
# would bloat the file for no gain, so anything under this is treated as
# continuous speech.
MIN_SPACING = 0.02


def read_env(key: str) -> str | None:
    """Look up a key in the repo's .env, a local .env, then the environment.

    Same resolution order as transcribe.py's load_api_key, but non-fatal:
    WhisperX only needs a token for diarization.
    """
    for candidate in [Path(__file__).resolve().parent.parent / ".env", Path(".env")]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    val = v.strip().strip('"').strip("'")
                    if val:
                        return val
    return os.environ.get(key) or None


def extract_audio(video_path: Path, dest: Path) -> None:
    """16kHz mono WAV — what Whisper expects, and what keeps RAM sane."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(dest),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def normalize_speaker(raw: str | None) -> str | None:
    """WhisperX says 'SPEAKER_00'; the rest of this skill says 'speaker_0'.

    pack_transcripts.py strips a 'speaker_' prefix and prints the remainder as
    the S-tag, so the numbering has to survive without the zero padding.
    """
    if not raw:
        return None
    text = str(raw)
    if text.upper().startswith("SPEAKER_"):
        suffix = text[len("SPEAKER_"):].lstrip("0") or "0"
        return f"speaker_{suffix}"
    return text


def whisperx_to_scribe(result: dict, language: str | None = None) -> dict:
    """WhisperX segments-of-words → the flat Scribe `words` list.

    Two details carry real weight:

    1. Gaps become explicit `spacing` entries. Without them every take reads
       as one unbroken phrase and the editor loses its cut candidates.
    2. Alignment can leave a word without timestamps (common for digits and
       symbols). Dropping those loses caption text, so each one inherits the
       previous word's end as a zero-length anchor and is kept.
    """
    words: list[dict] = []
    text_parts: list[str] = []
    prev_end: float | None = None
    undated = 0

    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            raw = (w.get("word") or w.get("text") or "").strip()
            if not raw:
                continue

            start = w.get("start")
            end = w.get("end")
            if start is None or end is None:
                # Keep the text, anchor it to the last known position.
                undated += 1
                start = prev_end if prev_end is not None else 0.0
                end = start
            start, end = float(start), float(end)
            if end < start:
                end = start

            if prev_end is not None and start - prev_end >= MIN_SPACING:
                words.append({
                    "type": "spacing",
                    "text": " ",
                    "start": round(prev_end, 3),
                    "end": round(start, 3),
                })

            entry = {
                "type": "word",
                "text": raw,
                "start": round(start, 3),
                "end": round(end, 3),
            }
            speaker = normalize_speaker(w.get("speaker") or segment.get("speaker"))
            if speaker:
                entry["speaker_id"] = speaker

            words.append(entry)
            text_parts.append(raw)
            prev_end = end

    return {
        "_engine": "whisperx",
        "language_code": language or result.get("language"),
        "text": " ".join(text_parts),
        "words": words,
        "_undated_words": undated,
    }


def pick_device(requested: str) -> tuple[str, str]:
    """Resolve (device, compute_type). CPU needs int8 or it is unusably slow."""
    if requested != "auto":
        device = requested
    else:
        try:
            import torch  # noqa: PLC0415 - optional, only needed to probe
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
    return device, ("float16" if device == "cuda" else "int8")


def transcribe_one(
    video: Path,
    edit_dir: Path,
    model_name: str = "large-v3",
    language: str | None = None,
    device: str = "auto",
    compute_type: str | None = None,
    diarize: bool = False,
    num_speakers: int | None = None,
    batch_size: int = 16,
    force: bool = False,
    verbose: bool = True,
) -> Path:
    """Transcribe one video. Returns the path to the transcript JSON.

    Cached: returns the existing path immediately unless force=True.
    """
    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{video.stem}.json"

    if out_path.exists() and not force:
        if verbose:
            print(f"cached: {out_path.name}")
        return out_path

    try:
        import whisperx  # noqa: PLC0415 - heavy import, only when actually running
    except ImportError:
        sys.exit(
            "whisperx not installed.\n"
            "Install it with:  pip install whisperx\n"
            "(or `pip install -e '.[whisperx]'` inside the video-use repo)\n"
            "A CUDA GPU makes this roughly an order of magnitude faster, but CPU works."
        )

    dev, auto_compute = pick_device(device)
    compute = compute_type or auto_compute

    if verbose:
        print(f"  {video.name}: {model_name} on {dev} ({compute})", flush=True)

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / f"{video.stem}.wav"
        extract_audio(video, wav)
        audio = whisperx.load_audio(str(wav))

        model = whisperx.load_model(model_name, dev, compute_type=compute, language=language)
        result = model.transcribe(audio, batch_size=batch_size)
        detected = result.get("language", language)

        # Alignment is what turns segment timings into per-word timings. It is
        # the whole reason to use WhisperX over plain Whisper here.
        if verbose:
            print(f"  aligning ({detected})", flush=True)
        align_model, metadata = whisperx.load_align_model(language_code=detected, device=dev)
        result = whisperx.align(
            result["segments"], align_model, metadata, audio, dev,
            return_char_alignments=False,
        )
        result["language"] = detected

        if diarize:
            token = read_env("HF_TOKEN")
            if not token:
                sys.exit(
                    "--diarize needs a HuggingFace token in HF_TOKEN (.env or environment).\n"
                    "You must also accept the terms for pyannote/speaker-diarization-3.1 once."
                )
            if verbose:
                print("  diarizing", flush=True)
            diarizer = whisperx.diarize.DiarizationPipeline(use_auth_token=token, device=dev)
            diar = diarizer(audio, num_speakers=num_speakers) if num_speakers else diarizer(audio)
            result = whisperx.assign_word_speakers(diar, result)

    payload = whisperx_to_scribe(result, language=detected)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    if verbose:
        dt = time.time() - t0
        n_words = sum(1 for w in payload["words"] if w["type"] == "word")
        kb = out_path.stat().st_size / 1024
        print(f"  saved: {out_path.name} ({kb:.1f} KB) in {dt:.1f}s — {n_words} words")
        if payload["_undated_words"]:
            print(f"    note: {payload['_undated_words']} word(s) had no timestamp after alignment")
        if n_words == 0:
            print("    warning: no speech detected — wrong --language, or a silent source?")

    return out_path


def collect_videos(target: Path) -> list[Path]:
    if target.is_dir():
        return sorted(p for p in target.iterdir() if p.is_file() and p.suffix in VIDEO_EXTS)
    return [target]


def main() -> None:
    ap = argparse.ArgumentParser(description="Local transcription with WhisperX, in Scribe format")
    ap.add_argument("target", type=Path, help="Video file or directory of videos")
    ap.add_argument("--edit-dir", type=Path, default=None,
                    help="Edit output directory (default: <video_parent>/edit)")
    ap.add_argument("--model", type=str, default="large-v3",
                    help="Whisper model: tiny, base, small, medium, large-v3 (default: large-v3)")
    ap.add_argument("--language", type=str, default=None,
                    help="ISO code such as 'de'. Omit to auto-detect per file.")
    ap.add_argument("--device", type=str, default="auto", choices=["auto", "cuda", "cpu"],
                    help="Compute device (default: auto-detect)")
    ap.add_argument("--compute-type", type=str, default=None,
                    help="Override precision (float16, int8, float32)")
    ap.add_argument("--batch-size", type=int, default=16,
                    help="Lower this if the GPU runs out of memory (default: 16)")
    ap.add_argument("--diarize", action="store_true", help="Label speakers (needs HF_TOKEN)")
    ap.add_argument("--num-speakers", type=int, default=None,
                    help="Speaker count when known. Improves diarization accuracy.")
    ap.add_argument("--force", action="store_true", help="Re-transcribe even if cached")
    args = ap.parse_args()

    target = args.target.resolve()
    if not target.exists():
        sys.exit(f"not found: {target}")

    videos = collect_videos(target)
    if not videos:
        sys.exit(f"no video files found in {target}")

    base = target if target.is_dir() else target.parent
    edit_dir = (args.edit_dir or (base / "edit")).resolve()

    print(f"whisperx: {len(videos)} source(s) → {edit_dir / 'transcripts'}/")

    # Sequential on purpose: one Whisper model already saturates a GPU, and
    # two large-v3 instances will exhaust VRAM rather than go faster.
    failures: list[tuple[Path, str]] = []
    for v in videos:
        try:
            transcribe_one(
                video=v,
                edit_dir=edit_dir,
                model_name=args.model,
                language=args.language,
                device=args.device,
                compute_type=args.compute_type,
                diarize=args.diarize,
                num_speakers=args.num_speakers,
                batch_size=args.batch_size,
                force=args.force,
            )
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            print(f"  FAILED {v.name}: {exc}")
            failures.append((v, str(exc)))

    if failures:
        sys.exit(f"{len(failures)} of {len(videos)} source(s) failed")


if __name__ == "__main__":
    main()
