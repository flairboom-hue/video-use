"""Animated overlay generation — PIL frames, ffmpeg encode.

Why not Remotion: it needs Node plus a per-project `npm install`, which is the
single most fragile step in a local install, and it renders in a headless
browser. PIL is already a dependency, renders deterministically, and produces
a transparent-capable PNG sequence that ffmpeg composites directly. The
trade-off is a smaller vocabulary of shapes, which is the right trade for an
MVP that has to actually run on the user's machine.

Every generator here returns a real .mov with an alpha channel. Nothing is
stubbed; if a style is not implemented it is not offered in the UI.

Style defaults are deliberately restrained — two accent colours, generous empty
space, no chrome. "Professional" in motion graphics mostly means *less*.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------- easing ---
# linear reads robotic; these are the two curves the skill's animation notes
# call for.

def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


# Captions occupy a band at the bottom of the frame (see captions.py MarginV).
# Graphics must stay above it — a chart with a subtitle across its middle is
# the most common failure of automated overlay placement.
CAPTION_SAFE_BOTTOM = 0.26   # fraction of frame height reserved for captions


@dataclass
class Style:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    accent: tuple[int, int, int] = (255, 90, 0)
    accent_2: tuple[int, int, int] = (90, 170, 255)
    text: tuple[int, int, int] = (255, 255, 255)
    muted: tuple[int, int, int] = (150, 150, 150)
    font_path: str = ""
    hold: float = 1.0          # freeze the landing frame before the cut
    reveal: float = 0.9        # how long the movement itself takes

    reserve_caption_band: bool = True

    @property
    def content_height(self) -> float:
        """Vertical space a graphic may use before the caption band starts.

        Reserved only when captions are actually burned in. Holding the band
        back on a video without captions just pushes every graphic into the
        top two thirds and leaves the frame looking unbalanced.
        """
        if not self.reserve_caption_band:
            return float(self.height)
        return self.height * (1 - CAPTION_SAFE_BOTTOM)

    @property
    def content_center_y(self) -> float:
        return self.content_height / 2

    def font(self, size: int) -> ImageFont.FreeTypeFont:
        candidates = [self.font_path] if self.font_path else []
        candidates += [
            "/System/Library/Fonts/Helvetica.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
        ]
        for c in candidates:
            if c and Path(c).exists():
                try:
                    return ImageFont.truetype(c, size)
                except OSError:
                    continue
        return ImageFont.load_default(size)


class GraphicsError(RuntimeError):
    pass


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _encode(frames_dir: Path, out: Path, fps: int) -> Path:
    """PNG sequence -> QuickTime Animation with alpha (composites cleanly)."""
    if not shutil.which("ffmpeg"):
        raise GraphicsError("ffmpeg not found on PATH — cannot encode the animation.")
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-framerate", str(fps),
         "-i", str(frames_dir / "f%05d.png"),
         "-c:v", "qtrle", "-pix_fmt", "argb", str(out)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not out.exists():
        raise GraphicsError(f"encoding failed: {proc.stderr[-400:]}")
    return out


def _render(draw_frame, duration: float, style: Style, out: Path) -> Path:
    total = max(1, int(duration * style.fps))
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for n in range(total):
            img = Image.new("RGBA", (style.width, style.height), (0, 0, 0, 0))
            draw_frame(ImageDraw.Draw(img), n / total, img)
            img.save(d / f"f{n:05d}.png")
        return _encode(d, out, style.fps)


# ------------------------------------------------------------ generators ---

def number_animation(out: Path, value: float, label: str = "", suffix: str = "",
                     style: Style | None = None, duration: float | None = None) -> Path:
    """A figure counting up, with its label. The workhorse."""
    st = style or Style()
    dur = duration or (st.reveal + st.hold)
    move = st.reveal / dur

    big = st.font(int(st.height * 0.22))
    small = st.font(int(st.height * 0.05))
    decimals = 0 if float(value).is_integer() else 1

    def frame(draw, t, img):
        p = ease_out_cubic(min(1.0, t / move)) if move > 0 else 1.0
        current = value * p
        text = f"{current:,.{decimals}f}".replace(",", ".") + suffix
        w, h = _text_size(draw, text, big)
        x, y = (st.width - w) / 2, st.content_center_y - h / 2
        draw.text((x, y), text, font=big, fill=(*st.accent, 255))
        if label:
            lw, _ = _text_size(draw, label.upper(), small)
            draw.text(((st.width - lw) / 2, y + h + st.height * 0.05),
                      label.upper(), font=small, fill=(*st.muted, 255))
    return _render(frame, dur, st, out)


def bar_chart(out: Path, values: list[float], labels: list[str] | None = None,
              style: Style | None = None, duration: float | None = None,
              suffix: str = "") -> Path:
    """Bars growing from the baseline, one after another, never in parallel.

    The eye cannot track two new things at once — staggering is not decoration.
    """
    st = style or Style()
    if not values:
        raise GraphicsError("bar_chart needs at least one value")
    dur = duration or (st.reveal + 0.25 * len(values) + st.hold)
    labels = labels or [""] * len(values)
    peak = max(values) or 1.0

    n = len(values)
    gap = st.width * 0.04
    area_w = st.width * 0.62
    bar_w = (area_w - gap * (n - 1)) / n
    left = (st.width - area_w) / 2
    base_y = st.content_height * 0.86
    max_h = st.content_height * 0.52

    value_font = st.font(int(st.height * 0.052))
    label_font = st.font(int(st.height * 0.032))
    stagger = 0.18

    def frame(draw, t, img):
        elapsed = t * dur
        for i, v in enumerate(values):
            local = (elapsed - i * stagger) / st.reveal
            p = ease_out_cubic(max(0.0, min(1.0, local)))
            if p <= 0:
                continue
            h = max_h * (v / peak) * p
            x0 = left + i * (bar_w + gap)
            colour = st.accent if i == n - 1 else st.accent_2
            draw.rounded_rectangle([x0, base_y - h, x0 + bar_w, base_y],
                                   radius=int(bar_w * 0.08), fill=(*colour, 255))
            shown = f"{v * p:,.0f}".replace(",", ".") + suffix
            tw, th = _text_size(draw, shown, value_font)
            draw.text((x0 + (bar_w - tw) / 2, base_y - h - th - st.height * 0.025),
                      shown, font=value_font, fill=(*st.text, 255))
            if labels[i]:
                lw, _ = _text_size(draw, labels[i].upper(), label_font)
                draw.text((x0 + (bar_w - lw) / 2, base_y + st.height * 0.022),
                          labels[i].upper(), font=label_font, fill=(*st.muted, 255))
    return _render(frame, dur, st, out)


def comparison(out: Path, before: float, after: float, label_before: str = "VORHER",
               label_after: str = "NACHHER", suffix: str = "",
               style: Style | None = None, duration: float | None = None) -> Path:
    """Two figures with an arrow — "von X auf Y" made visible."""
    st = style or Style()
    dur = duration or (st.reveal + 0.4 + st.hold)
    big = st.font(int(st.height * 0.13))
    small = st.font(int(st.height * 0.035))

    # The arrow must sit in the gap the numbers actually leave, not at a fixed
    # percentage — a wide value like "100 Mio" otherwise collides with the head.
    final_left = f"{before:,.0f}".replace(",", ".") + suffix
    final_right = f"{after:,.0f}".replace(",", ".") + suffix

    def frame(draw, t, img):
        elapsed = t * dur
        p1 = ease_out_cubic(max(0.0, min(1.0, elapsed / st.reveal)))
        p2 = ease_out_cubic(max(0.0, min(1.0, (elapsed - 0.35) / st.reveal)))
        cy = st.content_center_y
        cx_l, cx_r = st.width * 0.28, st.width * 0.72

        for value, prog, cx, colour, label in (
            (before, p1, cx_l, st.accent_2, label_before),
            (after, p2, cx_r, st.accent, label_after),
        ):
            if prog <= 0:
                continue
            text = f"{value * prog:,.0f}".replace(",", ".") + suffix
            w, h = _text_size(draw, text, big)
            draw.text((cx - w / 2, cy - h / 2), text, font=big,
                      fill=(*colour, int(255 * prog)))
            lw, _ = _text_size(draw, label.upper(), small)
            draw.text((cx - lw / 2, cy + h * 0.75), label.upper(), font=small,
                      fill=(*st.muted, int(255 * prog)))

        if p2 > 0:
            # Measure the finished labels so the gap does not move as they count up.
            lw, _ = _text_size(draw, final_left, big)
            rw, _ = _text_size(draw, final_right, big)
            gap_start = cx_l + lw / 2
            gap_end = cx_r - rw / 2
            pad = (gap_end - gap_start) * 0.18
            ax0, ax1_full = gap_start + pad, gap_end - pad
            if ax1_full > ax0:
                ax1 = ax0 + (ax1_full - ax0) * p2
                draw.line([ax0, cy, ax1, cy], fill=(*st.text, 255),
                          width=max(2, st.height // 240))
                if p2 > 0.6:
                    head = min(st.height * 0.016, (ax1 - ax0) * 0.5)
                    draw.polygon([(ax1, cy), (ax1 - head, cy - head), (ax1 - head, cy + head)],
                                 fill=(*st.text, 255))
    return _render(frame, dur, st, out)


def lower_third(out: Path, title: str, subtitle: str = "",
                style: Style | None = None, duration: float | None = None) -> Path:
    """Name plate that wipes in from the left and holds."""
    st = style or Style()
    dur = duration or (st.reveal + 2.0)
    title_font = st.font(int(st.height * 0.055))
    sub_font = st.font(int(st.height * 0.032))

    bar_x = st.width * 0.08
    bar_y = st.content_height * 0.80
    bar_h = st.height * 0.11

    def frame(draw, t, img):
        elapsed = t * dur
        p = ease_out_cubic(max(0.0, min(1.0, elapsed / st.reveal)))
        out_p = ease_in_out_cubic(max(0.0, min(1.0, (elapsed - (dur - 0.4)) / 0.4)))
        reveal = p * (1 - out_p)
        if reveal <= 0:
            return
        # The plate is sized to its content, not to a fixed fraction: a long
        # name would otherwise overflow a 42%-wide box.
        pad = st.height * 0.03
        tw, _ = _text_size(draw, title, title_font)
        sw, _ = _text_size(draw, subtitle.upper(), sub_font) if subtitle else (0, 0)
        full_w = max(tw, sw) + pad * 2 + st.height * 0.008

        width = full_w * reveal
        draw.rectangle([bar_x, bar_y, bar_x + width, bar_y + bar_h], fill=(15, 15, 15, 225))
        draw.rectangle([bar_x, bar_y, bar_x + st.height * 0.008, bar_y + bar_h],
                       fill=(*st.accent, 255))

        # Text only once the plate can actually hold it — fading it in earlier
        # makes the words spill past the wipe, which reads as a broken render.
        needed = full_w * 0.92
        if width >= needed:
            alpha = int(255 * min(1.0, (width - needed) / max(1.0, full_w * 0.08)))
            tx = bar_x + pad
            draw.text((tx, bar_y + bar_h * 0.14), title, font=title_font,
                      fill=(*st.text, alpha))
            if subtitle:
                draw.text((tx, bar_y + bar_h * 0.58), subtitle.upper(), font=sub_font,
                          fill=(*st.muted, alpha))
    return _render(frame, dur, st, out)


def text_animation(out: Path, text: str, style: Style | None = None,
                   duration: float | None = None) -> Path:
    """Kinetic type: words appear one at a time, centred on the full string.

    Centring on the *full* width matters — centring per partial string makes
    the line slide sideways as it builds, which reads as a bug.
    """
    st = style or Style()
    words = text.split()
    dur = duration or (0.22 * len(words) + st.hold)
    font = st.font(int(st.height * 0.085))
    per = (dur - st.hold) / max(1, len(words))

    def frame(draw, t, img):
        elapsed = t * dur
        shown = max(1, min(len(words), int(elapsed / per) + 1)) if per > 0 else len(words)
        full_w, h = _text_size(draw, text, font)
        x = (st.width - full_w) / 2
        y = st.content_center_y - h / 2
        cursor = x
        for i, w in enumerate(words[:shown]):
            local = ease_out_cubic(max(0.0, min(1.0, (elapsed - i * per) / 0.25)))
            ww, _ = _text_size(draw, w + " ", font)
            draw.text((cursor, y + (1 - local) * st.height * 0.02), w, font=font,
                      fill=(*(st.accent if i == len(words) - 1 else st.text),
                            int(255 * local)))
            cursor += ww
    return _render(frame, dur, st, out)


GENERATORS = {
    "number_animation": number_animation,
    "bar_chart": bar_chart,
    "comparison": comparison,
    "lower_third": lower_third,
    "text_animation": text_animation,
}


def available_kinds() -> list[str]:
    """Only what is actually implemented is offered — no dead menu entries."""
    return sorted(GENERATORS)
