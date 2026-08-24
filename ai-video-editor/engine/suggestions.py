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

# Up to three digits was fine for percentages and broke everything else: a
# devlog says "4200 Commits", not "42 Prozent". Grouped forms ("4.200",
# "4,200") count too, since ASR writes the separator either way.
NUMBER = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$|^\d{1,9}(?:[.,]\d{1,2})?$")
PERCENT_WORD = {"prozent", "percent", "%"}
CURRENCY = {"euro", "eur", "dollar", "usd", "millionen", "million", "milliarden",
            "billion", "tausend", "thousand", "k", "mio"}
# Finite verb forms, singular AND plural: people say "die Draw Calls fielen",
# not "die Draw Calls ist gefallen". Missing the plural made the detector
# silent on exactly the sentences a developer speaks.
GROWTH = {"gestiegen", "stieg", "stiegen", "steigt", "steigen", "gewachsen",
          "wuchs", "wuchsen", "wächst", "wachsen", "erhöht", "erhöhte",
          "verdoppelt", "verdoppelte", "verdreifacht", "mehr",
          "increased", "grew", "grows", "doubled", "tripled", "up", "more"}
DECLINE = {"gesunken", "sank", "sanken", "sinkt", "sinken", "gefallen",
           "fiel", "fielen", "fällt", "fallen", "reduziert", "reduzierte",
           "halbiert", "halbierte", "weniger",
           "decreased", "dropped", "fell", "halved", "down", "less"}

# A bare figure is only worth a graphic if it counts something the viewer can
# hold on to. Percent and currency were the original test, which made the
# detector useless outside a business report: a devlog says "4.200 Commits" or
# "18 Monate", and neither carries a percent sign or a currency.
# German ASR writes small numbers as words far more often than as digits, so a
# digits-only detector is deaf to "zwei Stunden" and "alle zehn Erfolge" —
# which is most of how people actually speak about small counts.
NUMBER_WORDS = {
    # "ein"/"eine" are articles far more often than numerals ("eine Datei"),
    # and counting them turns every sentence into a two-value comparison.
    # "eins" is the numeral and stays.
    "null": 0, "eins": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9,
    "zehn": 10, "elf": 11, "zwölf": 12, "zwoelf": 12, "zwanzig": 20,
    "dreißig": 30, "dreissig": 30, "fünfzig": 50, "fuenfzig": 50, "hundert": 100,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "twenty": 20,
}

UNITS = {
    # time
    "sekunde", "sekunden", "minute", "minuten", "stunde", "stunden",
    "tag", "tage", "woche", "wochen", "monat", "monate", "jahr", "jahre",
    "second", "seconds", "minute", "minutes", "hour", "hours",
    "day", "days", "week", "weeks", "month", "months", "year", "years",
    # making it
    "commit", "commits", "zeile", "zeilen", "bug", "bugs", "feature",
    "features", "build", "builds", "version", "versionen", "prototyp",
    "prototypen", "iteration", "iterationen", "entwürfe", "anläufe",
    "line", "lines", "iterations", "attempts", "versions",
    # what is in the game
    "level", "levels", "gegner", "gegnertypen", "boss", "bosse", "item",
    "items", "waffe", "waffen", "karte", "karten", "map", "maps", "welt",
    "welten", "track", "tracks", "song", "songs", "sound", "sounds",
    "animation", "animationen", "sprite", "sprites", "achievement",
    "achievements", "skin", "skins", "enemies", "worlds", "weapons",
    # people and reach
    "spieler", "spielerinnen", "tester", "wishlist", "wishlists",
    "download", "downloads", "review", "reviews", "follower", "abonnenten",
    "player", "players", "playtester", "subscribers", "wishlisted",
    # performance and rendering
    "fps", "frames", "ms", "kb", "mb", "gb", "shader", "shadern",
    "dreieck", "dreiecke", "polygon", "polygone", "draw", "drawcall",
    "drawcalls", "triangle", "triangles", "vertices",
    # things you make and ship
    "erfolg", "erfolge", "icon", "icons", "schnitt", "schnitte", "screenshot",
    "screenshots", "grafik", "grafiken", "zone", "zonen", "fehler", "bugs",
    "cut", "cuts", "asset", "assets",
    # attempts and rebuilds — what a devlog counts when it is being honest
    "runde", "runden", "anlauf", "anläufe", "anlaeufe", "ansatz", "ansätze",
    "ansaetze", "versuch", "versuche", "durchgang", "durchgänge", "entwurf",
    "entwürfe", "round", "rounds", "sprache", "sprachen", "language",
    "languages", "skript", "skripte", "script", "scripts", "datei", "dateien",
    # measures and contents — without these, "800 Meter, zehn Zonen" looks
    # comparable and becomes a chart chart of metres against zones
    "meter", "metern", "kilometer", "meters", "figur", "figuren", "charakter",
    "charaktere", "character", "characters", "kosmetikteil", "kosmetikteile",
    "teil", "teile", "objekt", "objekte", "einzelobjekte", "stelle", "stellen",
    "regelverstoß", "regelverstöße", "zeichenbefehl", "zeichenbefehle",
    "kollisionsfläche", "kollisionsflächen", "checkpoint", "checkpoints",
}

# A German plural or compound rarely equals the stem: "Schnitten",
# "Achievement-Icons", "Gegnertypen". Listing every inflection is a losing
# game, so a token counts if it opens or closes with a known stem.
UNIT_STEMS = tuple(sorted(UNITS, key=len, reverse=True))


def _unit_of(token: str) -> str:
    if token in UNITS:
        return token
    for stem in UNIT_STEMS:
        if len(stem) >= 4 and (token.startswith(stem) or token.endswith(stem)):
            return stem
    return ""
COMPARISON = {"von", "auf", "from", "to", "versus", "vs", "gegenüber", "compared"}
ORDINALS = {"erstens", "zweitens", "drittens", "viertens",
            "first", "second", "third", "fourth", "finally", "zuletzt"}
TIME_MARKERS = {"jahr", "jahre", "monat", "woche", "year", "years", "month",
                "week", "zeitraum", "timeline", "seit", "since"}
# Place detection without an NER model: a capitalized token that is not a
# sentence opener and not a known non-place capitalized word.
PLACE_HINTS = {"in", "nach", "aus", "bei", "von", "to", "from", "at"}

# German capitalises every noun, so "capitalised word after a preposition" is
# not a proper-noun signal at all — it fires on "besteht aus Kugeln" and "Post
# vom Gartenamt". A locative VERB somewhere in the sentence is the discriminator
# that actually separates "wir waren in Tokio" from "aus Kugeln zusammengesetzt".
LOCATIVE_VERBS = {
    "war", "waren", "warst", "gewesen", "besucht", "besuchte", "gereist",
    "geflogen", "gefahren", "gelebt", "wohnte", "wohnten", "landete",
    "angekommen", "unterwegs", "urlaub",
    "visited", "went", "travelled", "traveled", "flew", "lived", "stayed",
}

STOP_CAPS = {"Ich", "Wir", "Du", "Sie", "Er", "Es", "Das", "Der", "Die", "Ein",
             "Eine", "Und", "Aber", "Dann", "Also", "Heute", "Hier", "I", "We",
             "You", "They", "The", "This", "That", "And", "But", "So", "Today"}

GRAPHIC_KINDS = [
    "number_animation", "bar_chart", "pie_chart", "comparison",
    "timeline", "icon_row", "infographic", "text_animation", "map", "custom",
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
            bare = token.replace("%", "")
            if not (NUMBER.match(bare) or bare in NUMBER_WORDS):
                continue

            context = {_norm(words[j].text) for j in range(max(a, i - 3), min(b, i + 3) + 1)}
            is_pct = bool(context & PERCENT_WORD) or "%" in words[i].text
            is_money = bool(context & CURRENCY)
            direction = "up" if context & GROWTH else ("down" if context & DECLINE else "")

            # The unit has to FOLLOW the figure — "18 Monate", not "Monate 18".
            # Scanning both directions would fire on any number in a sentence
            # that happens to mention a unit somewhere.
            unit = ""
            for j in range(i + 1, min(b, i + 3) + 1):
                unit = _unit_of(_norm(words[j].text))
                if unit:
                    break

            # A bare number with nothing to count ("zwei Dinge") is not a graphic.
            if not (is_pct or is_money or direction or unit):
                continue

            values = []
            unit_by_value: dict[int, str] = {}
            for j in range(a, b + 1):
                tok = _norm(words[j].text).replace("%", "")
                if NUMBER.match(tok):
                    values.append(tok)
                elif tok in NUMBER_WORDS:
                    values.append(str(NUMBER_WORDS[tok]))
                else:
                    continue
                # The unit this particular figure carries, if any.
                own = ""
                for k in range(j + 1, min(b, j + 3) + 1):
                    own = _unit_of(_norm(words[k].text))
                    if own:
                        break
                unit_by_value[len(values) - 1] = own
            has_pair = len(values) >= 2 and bool(context & COMPARISON)

            # Percentages that add up to roughly a whole are shares of one
            # thing, which is what a pie says and a bar chart does not.
            numeric = [float(v.replace(",", ".")) for v in values
                       if v.replace(",", ".").replace(".", "").isdigit()]
            is_whole = (is_pct and len(numeric) >= 3
                        and 92 <= sum(numeric) <= 108)

            # Bars compare like with like. "In zwei Tagen kamen neun Fehler"
            # has two figures and nothing to compare — charting days against
            # bugs is a graphic that means nothing. Only build one when the
            # figures carry no CONFLICTING unit.
            named_units = {u for u in unit_by_value.values() if u}
            comparable = len(named_units) <= 1

            # A "bar chart" of one bar communicates nothing — it is a number.
            if is_whole:
                kind = "pie_chart"
            elif has_pair and comparable:
                kind = "comparison"
            elif len(values) >= 2 and comparable:
                kind = "bar_chart"
            else:
                kind = "number_animation"
            confidence = (0.9 if (is_pct and direction)
                          else 0.75 if is_pct or is_money
                          else 0.7 if (unit and direction)
                          else 0.6)

            anchor_idx = i
            if not comparable:
                for j in range(b, a - 1, -1):
                    tok = _norm(words[j].text).replace("%", "")
                    if not (NUMBER.match(tok) or tok in NUMBER_WORDS):
                        continue
                    if any(_unit_of(_norm(words[k].text))
                           for k in range(j + 1, min(b, j + 3) + 1)):
                        anchor_idx = j
                        break

            out.append(Suggestion(
                id=f"g{len(out)}_{i}", kind="graphic", graphic_kind=kind,
                anchor_word=words[anchor_idx].text,
                anchor_occurrence=_occurrence_index(words, anchor_idx),
                start=words[i].start, end=words[b].end, quote=_quote(words, a, b),
                reason=("A percentage with a direction of change — a chart makes it land"
                        if is_pct and direction else
                        f"A figure the viewer has to hold in their head ({unit}) — show it"
                        if unit else
                        "A figure the viewer has to hold in their head — show it"),
                confidence=confidence,
                payload={"values": values, "percent": is_pct, "currency": is_money,
                         "direction": direction, "unit": unit},
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
    # Up to five points read better as labelled icons than as a text list;
    # beyond that the row stops fitting and a plain infographic is honest.
    graphic = "icon_row" if len(hits) <= 5 else "infographic"
    return [Suggestion(
        id=f"g_list_{i}", kind="graphic", graphic_kind=graphic,
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
        sentence = {_norm(w.text) for w in words[a:b + 1]}
        if not sentence & LOCATIVE_VERBS:
            continue
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


def select_pending(suggestions: list[dict], kind: str | None = None,
                   graphic_kind: str | None = None,
                   min_confidence: float = 0.0) -> list[str]:
    """Ids of the pending proposals a bulk action should apply to.

    Only `pending` ones: a bulk action must never silently re-apply something
    the user already decided. An over-narrow filter returns an empty list —
    never a fallback to "everything", which is the dangerous failure here.
    """
    return [
        s["id"] for s in suggestions
        if s.get("status") == "pending"
        and (kind is None or s.get("kind") == kind)
        and (graphic_kind is None or s.get("graphic_kind") == graphic_kind)
        and float(s.get("confidence", 0) or 0) >= min_confidence
    ]


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
