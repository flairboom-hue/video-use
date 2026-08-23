"""The automatic rough cut.

Four passes over the material, each removing a different kind of waste:

  1. silence      — auto-editor's loudness analysis
  2. fillers      — "ähm", "uh", "sozusagen" and friends, from the transcript
  3. repetitions  — the same phrase twice in a row is a retake, keep the last
  4. false starts — an abandoned fragment right before a restart

Nothing here touches the source file. Every pass produces *ranges to remove*,
which are merged and inverted into keep-ranges at the end. The result is an
edit decision list; the original is never rewritten.

Two safety rules from the video-use skill apply throughout and are the reason
this is not a naive filter:

  - A silence shorter than MIN_GAP is not cuttable. It lands mid-phrase and
    clips consonants.
  - Every cut edge is padded. ASR timestamps drift 50-100ms and padding
    absorbs it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict, field
from pathlib import Path

from .transcribe import Transcript, Word

# Cut-craft constants, in seconds. See SKILL.md "Cut craft" for the reasoning.
MIN_GAP = 0.15          # silences shorter than this are unsafe to cut
MIN_CLIP = 0.40         # kept fragments shorter than this are breaths
PAD_BEFORE = 0.05       # Hard Rule 7 working window is 30-200ms
PAD_AFTER = 0.08

FILLERS = {
    "de": {"äh", "ähm", "öh", "öhm", "hm", "hmm", "also", "halt", "quasi",
           "sozusagen", "irgendwie", "eigentlich", "genau", "ne", "nö"},
    "en": {"uh", "um", "uhm", "er", "erm", "like", "basically", "actually",
           "literally", "sorta", "kinda", "yeah"},
}
# Words that are fillers only when isolated — cutting them mid-sentence breaks
# grammar, so they are removed only when they stand alone between pauses.
CONTEXTUAL = {"also", "halt", "eigentlich", "genau", "like", "actually", "literally"}


@dataclass
class Removal:
    start: float
    end: float
    reason: str
    detail: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = round(self.duration, 3)
        return d


@dataclass
class RoughCut:
    keep: list[tuple[float, float]] = field(default_factory=list)
    removals: list[Removal] = field(default_factory=list)
    source_duration: float = 0.0

    @property
    def kept_duration(self) -> float:
        return sum(e - s for s, e in self.keep)

    def stats(self) -> dict:
        by_reason: dict[str, dict] = {}
        for r in self.removals:
            entry = by_reason.setdefault(r.reason, {"count": 0, "seconds": 0.0})
            entry["count"] += 1
            entry["seconds"] = round(entry["seconds"] + r.duration, 2)
        removed = self.source_duration - self.kept_duration
        return {
            "source_duration": round(self.source_duration, 2),
            "kept_duration": round(self.kept_duration, 2),
            "removed_seconds": round(removed, 2),
            "removed_pct": round(removed / self.source_duration * 100, 1)
            if self.source_duration else 0.0,
            "segments": len(self.keep),
            "by_reason": by_reason,
        }


def normalize(text: str) -> str:
    return re.sub(r"[^\w]", "", text, flags=re.UNICODE).lower()


# ---------------------------------------------------------------- silence ---

def detect_silence(video: Path, margin: str = "0.05s,0.08s",
                   threshold: float | None = None) -> list[tuple[float, float]]:
    """Loud ranges from auto-editor. Returns [] when auto-editor is absent.

    Absence is not an error: the transcript-driven passes still work, the cut
    is just less aggressive. The caller reports which passes actually ran.
    """
    exe = shutil.which("auto-editor")
    if not exe:
        return []

    cmd = [exe, str(video), "--export", "v1", "--margin", margin, "--no-open", "-q"]
    if threshold is not None:
        cmd += ["--edit", f"audio:threshold={threshold}"]

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "chunks.v1"
        proc = subprocess.run(cmd + ["-o", str(out)], capture_output=True, text=True)
        if proc.returncode != 0 or not out.exists():
            return []
        import json
        payload = json.loads(out.read_text())

    fps = _probe_fps(video)
    if not fps:
        return []

    loud: list[tuple[float, float]] = []
    for start_f, end_f, speed in payload.get("chunks", []):
        if float(speed) != 1.0:      # 99999 == cut; other speeds are not ours to interpret
            continue
        a, b = int(start_f) / fps, int(end_f) / fps
        if b > a:
            loud.append((a, b))
    return loud


def _probe_fps(video: Path) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", f"stream={key}",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True)
        raw = (p.stdout or "").strip()
        num, _, den = raw.partition("/")
        try:
            fps = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            continue
        if fps > 0:
            return fps
    return 0.0


# ---------------------------------------------------------------- fillers ---

def detect_fillers(transcript: Transcript, language: str = "de",
                   gap_before: float = 0.25) -> list[Removal]:
    """Filler words. Contextual ones only count when they stand alone.

    "Also" opening a sentence is a filler; "also" inside a clause is grammar.
    The discriminator used here is an audible pause on at least one side.
    """
    vocab = FILLERS.get(language, set()) | FILLERS["en"]
    out: list[Removal] = []
    words = transcript.words

    for i, w in enumerate(words):
        token = normalize(w.text)
        if token not in vocab:
            continue
        if token in CONTEXTUAL:
            gap_l = w.start - words[i - 1].end if i > 0 else 999.0
            gap_r = words[i + 1].start - w.end if i + 1 < len(words) else 999.0
            if gap_l < gap_before and gap_r < gap_before:
                continue
        out.append(Removal(start=w.start, end=w.end, reason="filler", detail=w.text))
    return out


# ------------------------------------------------------------ repetitions ---

def detect_repetitions(transcript: Transcript, window: int = 6,
                       min_words: int = 3, max_gap: float = 4.0) -> list[Removal]:
    """A phrase said twice within a few seconds is a retake — keep the later one.

    Speakers restart a sentence when they flub it, and the second attempt is
    almost always the keeper. Removing the *first* occurrence keeps the take
    that the speaker themselves chose to end on.
    """
    words = transcript.words
    tokens = [normalize(w.text) for w in words]
    out: list[Removal] = []
    consumed: set[int] = set()

    for size in range(window, min_words - 1, -1):
        for i in range(len(tokens) - 2 * size + 1):
            if any(j in consumed for j in range(i, i + size)):
                continue
            first = tokens[i:i + size]
            if not all(first):
                continue
            second = tokens[i + size:i + 2 * size]
            if first != second:
                continue
            gap = words[i + size].start - words[i + size - 1].end
            if gap > max_gap:
                continue
            out.append(Removal(
                start=words[i].start, end=words[i + size - 1].end,
                reason="repetition", detail=" ".join(words[j].text for j in range(i, i + size)),
            ))
            consumed.update(range(i, i + 2 * size))
    return out


# ----------------------------------------------------------- false starts ---

def detect_false_starts(transcript: Transcript, max_fragment: int = 4,
                        min_pause: float = 0.6) -> list[Removal]:
    """A short fragment abandoned before a long pause, then a fresh start.

    Deliberately conservative: only fragments that both end in a real pause and
    are followed by a capitalized restart count, because an aggressive rule here
    eats real sentences.
    """
    words = transcript.words
    out: list[Removal] = []
    sentence_start = 0

    for i, w in enumerate(words[:-1]):
        pause = words[i + 1].start - w.end
        if pause < min_pause:
            continue
        length = i - sentence_start + 1
        ends_clean = w.text.rstrip()[-1:] in ".!?"
        next_is_restart = words[i + 1].text[:1].isupper()

        if length <= max_fragment and not ends_clean and next_is_restart:
            out.append(Removal(
                start=words[sentence_start].start, end=w.end,
                reason="false_start",
                detail=" ".join(x.text for x in words[sentence_start:i + 1]),
            ))
        sentence_start = i + 1
    return out


# ---------------------------------------------------------------- assembly ---

def _merge(ranges: list[tuple[float, float]], tolerance: float = 0.0) -> list[tuple[float, float]]:
    if not ranges:
        return []
    ordered = sorted(ranges)
    merged = [list(ordered[0])]
    for a, b in ordered[1:]:
        if a <= merged[-1][1] + tolerance:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def _invert(removals: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for a, b in _merge(removals):
        if a > cursor:
            keep.append((cursor, min(a, duration)))
        cursor = max(cursor, b)
    if cursor < duration:
        keep.append((cursor, duration))
    return [(a, b) for a, b in keep if b > a]


def apply_safety(keep: list[tuple[float, float]], min_gap: float = MIN_GAP,
                 min_clip: float = MIN_CLIP) -> list[tuple[float, float]]:
    """Re-join unsafely short silences, then drop sub-threshold fragments.

    Merging runs first so two short neighbours separated by a hairline gap can
    add up to one segment that clears min_clip, instead of both being discarded.
    """
    if not keep:
        return []
    merged = [list(keep[0])]
    for a, b in keep[1:]:
        if a - merged[-1][1] < min_gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged if b - a >= min_clip]


def build(video: Path, transcript: Transcript | None, duration: float,
          language: str = "de", use_silence: bool = True,
          remove_fillers: bool = True, remove_repetitions: bool = True,
          remove_false_starts: bool = True) -> RoughCut:
    """Run the enabled passes and produce keep-ranges plus a removal log."""
    removals: list[Removal] = []
    silence_keep: list[tuple[float, float]] | None = None

    if use_silence:
        loud = detect_silence(video)
        if loud:
            silence_keep = loud
            for a, b in _invert(loud, duration):
                removals.append(Removal(start=a, end=b, reason="silence"))

    if transcript and transcript.words:
        if remove_fillers:
            removals += detect_fillers(transcript, language)
        if remove_repetitions:
            removals += detect_repetitions(transcript)
        if remove_false_starts:
            removals += detect_false_starts(transcript)

    keep = _invert([(r.start, r.end) for r in removals], duration) if removals \
        else [(0.0, duration)]

    # Intersect with auto-editor's loud ranges so the transcript passes cannot
    # re-introduce silence that the loudness analysis already excluded.
    if silence_keep:
        keep = _intersect(keep, _merge(silence_keep))

    keep = apply_safety(keep)
    keep = [(max(0.0, a - PAD_BEFORE), min(duration, b + PAD_AFTER)) for a, b in keep]
    keep = _merge(keep)

    return RoughCut(keep=keep, removals=sorted(removals, key=lambda r: r.start),
                    source_duration=duration)


def _intersect(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    i = j = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if hi > lo:
            out.append((lo, hi))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out
