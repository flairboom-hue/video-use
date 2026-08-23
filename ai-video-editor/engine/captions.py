"""Caption tracks as styled ASS — word highlighting included.

SRT cannot express per-word emphasis, so the animated styles are written as
ASS with karaoke timing (\\k), which ffmpeg's subtitles filter renders natively.
No extra renderer, no browser.

MarginV is a platform rule, not taste. TikTok / Reels / Shorts UI covers
roughly the bottom 25-30% of a 1080x1920 frame; libass scales against
PlayResY, so the values below keep captions clear of that furniture on every
aspect ratio.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .transcribe import Transcript, Word


@dataclass
class CaptionStyle:
    key: str
    label: str
    font: str = "DejaVu Sans"
    size: int = 18
    bold: bool = True
    primary: str = "&H00FFFFFF"     # ASS is &HAABBGGRR
    highlight: str = "&H000090FF"   # the accent, applied to the spoken word
    outline: str = "&H00000000"
    outline_width: int = 2
    shadow: int = 0
    alignment: int = 2              # 2 = bottom centre
    margin_v: int = 90
    words_per_cue: int = 2
    uppercase: bool = True
    karaoke: bool = False


STYLES: dict[str, CaptionStyle] = {
    "bold_center": CaptionStyle(
        key="bold_center", label="Bold Center — 2 words, uppercase",
        words_per_cue=2, uppercase=True),
    "word_highlight": CaptionStyle(
        key="word_highlight", label="Word Highlight — line builds, spoken word accented",
        words_per_cue=5, uppercase=True, karaoke=True, size=17),
    "clean_lower": CaptionStyle(
        key="clean_lower", label="Clean Lower — sentence case, discreet",
        words_per_cue=7, uppercase=False, size=15, margin_v=60, bold=False),
    "big_impact": CaptionStyle(
        key="big_impact", label="Big Impact — one word at a time",
        words_per_cue=1, uppercase=True, size=26, outline_width=3),
}


def available_styles() -> list[dict]:
    return [{"key": s.key, "label": s.label} for s in STYLES.values()]


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _header(style: CaptionStyle, width: int, height: int) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{style.font},{style.size},{style.primary},{style.highlight},{style.outline},&H00000000,{-1 if style.bold else 0},0,0,0,100,100,0,0,1,{style.outline_width},{style.shadow},{style.alignment},40,40,{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_ass(words: list[Word], style: CaptionStyle, out_path: Path,
              width: int = 288, height: int = 288) -> Path:
    """Word list (already on the OUTPUT timeline) -> .ass file."""
    lines = [_header(style, width, height)]

    for i in range(0, len(words), style.words_per_cue):
        chunk = words[i:i + style.words_per_cue]
        if not chunk:
            continue
        start, end = chunk[0].start, chunk[-1].end
        if end <= start:
            end = start + 0.4

        if style.karaoke and len(chunk) > 1:
            # \k durations are in centiseconds and must tile the whole cue,
            # otherwise the highlight drifts away from the audio.
            parts = []
            for w in chunk:
                cs = max(1, int(round((w.end - w.start) * 100)))
                text = w.text.upper() if style.uppercase else w.text
                parts.append(f"{{\\k{cs}}}{_escape(text)}")
            body = " ".join(parts)
        else:
            text = " ".join(w.text for w in chunk)
            body = _escape(text.upper() if style.uppercase else text)

        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Main,,0,0,0,,{body}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def words_on_output_timeline(transcript: Transcript,
                             clips: list[tuple[float, float]]) -> list[Word]:
    """Map source-time words onto the cut timeline.

        output_time = word.start - clip_start + clip_offset

    Getting this wrong drifts captions further out of sync with every clip —
    the classic silent failure of an automated edit.
    """
    out: list[Word] = []
    offset = 0.0
    for c_start, c_end in clips:
        for w in transcript.words:
            if w.end <= c_start or w.start >= c_end:
                continue
            s = max(w.start, c_start) - c_start + offset
            e = min(w.end, c_end) - c_start + offset
            if e > s:
                out.append(Word(text=w.text, start=s, end=e, speaker=w.speaker))
        offset += c_end - c_start
    return out


def play_res_for(width: int, height: int, base: int = 288) -> tuple[int, int]:
    """ASS coordinates scaled to the target frame's aspect.

    libass interprets MarginV against PlayResY. A square PlayRes on a 9:16
    frame therefore pushes captions towards the middle of the picture instead
    of the lower third — which is exactly where the platform UI is not.
    """
    if width <= 0 or height <= 0:
        return base, base
    if height >= width:
        return max(1, round(base * width / height)), base
    return base, max(1, round(base * height / width))


def build_for_project(transcript: Transcript, clips: list[tuple[float, float]],
                      style_key: str, out_path: Path,
                      width: int = 1920, height: int = 1080) -> Path:
    style = STYLES.get(style_key) or STYLES["bold_center"]
    rx, ry = play_res_for(width, height)
    return build_ass(words_on_output_timeline(transcript, clips), style,
                     out_path, rx, ry)
