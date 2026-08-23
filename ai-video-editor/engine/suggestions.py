"""Where visual support would actually help.

This is the human-in-the-loop half of the pipeline. It never edits anything —
it produces *proposals* anchored to spoken words, each with a confidence and a
concrete reason, and the user accepts, changes or rejects each one.

Design decision: detection is rule-based on the transcript, not LLM-driven.
Three reasons. It runs with no model installed, it is deterministic enough to
test, and a false positive here costs the user a click rather than a wrong
edit. The optional LLM pass (llm.py) only *reranks and phrases* what these
rules already found — it does not invent anchors, because an invented
timestamp would place a graphic over the wrong sentence.

Every suggestion carries `anchor_word`, not a timestamp, so it survives a
re-cut: see helpers/render.py's overlay anchoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from pathlib import Path

from .transcribe import Transcript, Word

# ---------------------------------------------------------------- patterns ---

NUMBER = re.compile(r"^\d{1,3}(?:[.,]\d+)?$")
PERCENT_WORD = {"prozent", "percent", "%"}
CURRENCY = {"euro", "eur", "dollar", "usd", "millionen", "million", "milliarden",
            "billion", "tausend", "thousand", "k", "mio"}
GROWTH = {"gestiegen", "gewachsen", "erhöht", "verdoppelt", "verdreifacht",
          "increased", "grew", "doubled", "tripled", "up"}
DECLINE = {"gesunken", "gefallen", "reduziert", "halbiert",
           "decreased", "dropped", "fell", "halved", "down"}
COMPARISON = {"von", "auf", "from", "to", "versus", "vs", "gegenüber", "compared"}
ORDINALS = {"erstens", "zweitens", "drittens", "viertens",
            "first", "second", "third", "fourth", "finally", "zuletzt"}
TIME_MARKERS = {"jahr", "jahre", "monat", "woche", "year", "years", "month",
                "week", "zeitraum", "timeline", "seit", "since"}
# Place detection without an NER model: a capitalized token that is not a
# sentence opener and not a known non-place capitalized word.
PLACE_HINTS = {"in", "nach", "aus", "bei", "von", "to", "from", "at", "visited",
               "besucht", "waren", "war", "gewesen"}

STOP_CAPS = {"Ich", "Wir", "Du", "Sie", "Er", "Es", "Das", "Der", "Die", "Ein",
             "Eine", "Und", "Aber", "Dann", "Also", "Heute", "Hier", "I", "We",
             "You", "They", "The", "This", "That", "And", "But", "So", "Today"}

GRAPHIC_KINDS = [
    "number_animation", "bar_chart", "pie_chart", "comparison",
    "timeline", "infographic", "icons", "text_animation", "map", "custom",
]


@dataclass
class Suggestion:
    id: str
    kind: str                 # graphic | broll | emphasis
    graphic_kind: str = ""    # one of GRAPHIC_KINDS when kind == "graphic"
    anchor_word: str = ""     # what it is pinned to, not when
    anchor_occurrence: int = 1
    start: float = 0.0        # informational: where it currently lands
    end: float = 0.0
    quote: str = ""           # the sentence it came from
    reason: str = ""          # why this was proposed, shown to the user
    confidence: float = 0.5
    payload: dict = field(default_factory=dict)   # numbers/labels for the generator
    status: str = "pending"   # pending | accepted | rejected | deferred

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ helpers ---

def _norm(text: str) -> str:
    return re.sub(r"[^\w%]", "", text, flags=re.UNICODE).lower()


def _sentences(words: list[Word], max_gap: float = 0.7) -> list[tuple[int, int]]:
    """Sentence spans as (start_index, end_index_inclusive).

    Split on terminal punctuation or a long pause — speech does not reliably
    carry punctuation, so the pause is the more dependable signal.
    """
    spans: list[tuple[int, int]] = []
    start = 0
    for i, w in enumerate(words):
        ends = w.text.rstrip()[-1:] in ".!?"
        gap = words[i + 1].start - w.end if i + 1 < len(words) else 999.0
        if ends or gap >= max_gap or i == len(words) - 1:
            spans.append((start, i))
            start = i + 1
    return [s for s in spans if s[0] <= s[1]]


def _quote(words: list[Word], a: int, b: int) -> str:
    return " ".join(w.text for w in words[a:b + 1]).strip()


def _occurrence_index(words: list[Word], upto: int) -> int:
    """Which occurrence of this token index `upto` is — needed by the anchor."""
    token = _norm(words[upto].text)
    return sum(1 for w in words[:upto + 1] if _norm(w.text) == token)


# --------------------------------------------------------------- detectors ---

def _numbers(words: list[Word], spans: list[tuple[int, int]]) -> list[Suggestion]:
    out: list[Suggestion] = []
    for a, b in spans:
        for i in range(a, b + 1):
            token = _norm(words[i].text)
            if not NUMBER.match(token.replace("%", "")):
                continue

            context = {_norm(words[j].text) for j in range(max(a, i - 3), min(b, i + 3) + 1)}
            is_pct = bool(context & PERCENT_WORD) or "%" in words[i].text
            is_money = bool(context & CURRENCY)
            direction = "up" if context & GROWTH else ("down" if context & DECLINE else "")

            # A bare small number ("zwei Dinge") is not worth a graphic.
            if not (is_pct or is_money or direction):
                continue

            values = [_norm(words[j].text) for j in range(a, b + 1)
                      if NUMBER.match(_norm(words[j].text).replace("%", ""))]
            has_pair = len(values) >= 2 and bool(context & COMPARISON)

            # A "bar chart" of one bar communicates nothing — it is a number.
            # Bars only earn their place once there is something to compare to.
            if has_pair:
                kind = "comparison"
            elif len(values) >= 2:
                kind = "bar_chart"
            else:
                kind = "number_animation"
            confidence = 0.9 if (is_pct and direction) else 0.75 if is_pct or is_money else 0.6

            out.append(Suggestion(
                id=f"g{len(out)}_{i}", kind="graphic", graphic_kind=kind,
                anchor_word=words[i].text, anchor_occurrence=_occurrence_index(words, i),
                start=words[i].start, end=words[b].end, quote=_quote(words, a, b),
                reason=("A percentage with a direction of change — a chart makes it land"
                        if is_pct and direction else
                        "A figure the viewer has to hold in their head — show it"),
                confidence=confidence,
                payload={"values": values, "percent": is_pct, "currency": is_money,
                         "direction": direction},
            ))
            break   # one graphic per sentence is plenty
    return out


def _lists(words: list[Word], spans: list[tuple[int, int]]) -> list[Suggestion]:
    hits: list[tuple[int, int, int]] = []
    for a, b in spans:
        for i in range(a, b + 1):
            if _norm(words[i].text) in ORDINALS:
                hits.append((i, a, b))
                break
    if len(hits) < 2:      # one "erstens" is a figure of speech, not a list
        return []
    i, a, b = hits[0]
    return [Suggestion(
        id=f"g_list_{i}", kind="graphic", graphic_kind="infographic",
        anchor_word=words[i].text, anchor_occurrence=_occurrence_index(words, i),
        start=words[i].start, end=words[hits[-1][2]].end, quote=_quote(words, a, b),
        reason=f"An enumerated list of {len(hits)} points — a build-on list keeps them straight",
        confidence=0.8, payload={"items": len(hits)},
    )]


def _timeline(words: list[Word], spans: list[tuple[int, int]]) -> list[Suggestion]:
    out: list[Suggestion] = []
    for a, b in spans:
        context = {_norm(words[j].text) for j in range(a, b + 1)}
        years = [w for w in words[a:b + 1] if re.fullmatch(r"(19|20)\d{2}", _norm(w.text))]
        if len(years) >= 2 or (years and context & TIME_MARKERS):
            i = words.index(years[0])
            out.append(Suggestion(
                id=f"g_time_{i}", kind="graphic", graphic_kind="timeline",
                anchor_word=years[0].text, anchor_occurrence=_occurrence_index(words, i),
                start=years[0].start, end=words[b].end, quote=_quote(words, a, b),
                reason="Several points in time in one sentence — a timeline beats narration",
                confidence=0.7, payload={"years": [_norm(y.text) for y in years]},
            ))
    return out


def _places(words: list[Word], spans: list[tuple[int, int]]) -> list[Suggestion]:
    """B-roll candidates. Capitalized token preceded by a locative preposition."""
    out: list[Suggestion] = []
    for a, b in spans:
        for i in range(a + 1, b + 1):
            token = words[i].text.strip(".,!?")
            if not token[:1].isupper() or token in STOP_CAPS or len(token) < 3:
                continue
            if _norm(words[i - 1].text) not in PLACE_HINTS:
                continue
            out.append(Suggestion(
                id=f"b_{i}", kind="broll",
                anchor_word=words[i].text, anchor_occurrence=_occurrence_index(words, i),
                start=words[i].start, end=words[b].end, quote=_quote(words, a, b),
                reason=f"A named place — B-roll of {token} covers this line",
                confidence=0.6, payload={"query": token},
            ))
            break
    return out


def detect(transcript: Transcript, min_confidence: float = 0.55,
           max_suggestions: int = 12) -> list[Suggestion]:
    """All detectors, deduplicated by anchor, strongest first.

    Capped deliberately: a wall of 40 proposals is worse than six good ones,
    because the user stops reading them.
    """
    words = transcript.words
    if not words:
        return []
    spans = _sentences(words)

    found = _numbers(words, spans) + _lists(words, spans) + \
        _timeline(words, spans) + _places(words, spans)

    found = [s for s in found if s.confidence >= min_confidence]
    found.sort(key=lambda s: (-s.confidence, s.start))

    seen: set[tuple[str, int]] = set()
    unique: list[Suggestion] = []
    for s in found:
        key = (_norm(s.anchor_word), s.anchor_occurrence)
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)

    unique.sort(key=lambda s: s.start)
    return unique[:max_suggestions]


def match_broll(suggestion: Suggestion, library: Path) -> list[str]:
    """Find local B-roll whose filename matches the suggestion's query.

    Filename matching only. A real semantic index over the B-roll library is a
    worthwhile next step, but pretending a keyword match is semantic search
    would be exactly the kind of fake capability this project avoids.
    """
    query = str(suggestion.payload.get("query", "")).lower()
    if not query or not library.is_dir():
        return []
    exts = {".mp4", ".mov", ".mkv", ".webm", ".jpg", ".jpeg", ".png"}
    return sorted(
        str(p) for p in library.rglob("*")
        if p.is_file() and p.suffix.lower() in exts and query in p.stem.lower()
    )
