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
PLACEMENTS = ("center", "top", "bottom")


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

    # Legibility over unknown footage. A graphic composites onto whatever the
    # camera shot, so its own colours are only half the problem: white text on
    # a bright kitchen wall is invisible no matter how good the palette is.
    outline: tuple[int, int, int, int] | None = None   # per-glyph contour
    outline_width: int = 0
    panel: tuple[int, int, int, int] | None = None     # backing card behind it
    panel_radius: float = 0.02      # fraction of frame height
    panel_inset: float = 0.06       # fraction of frame width

    # Motion blur by temporal supersampling: render this many sub-frames per
    # output frame across the shutter interval and average them. 0 disables it.
    # This is what a real shutter does; a directional blur filter applied
    # afterwards cannot know which pixels were moving or how fast.
    motion_blur: int = 0
    shutter: float = 0.5            # fraction of the frame interval the shutter is open

    reserve_caption_band: bool = True

    # Where in the frame the graphic sits. A card is a full-width plate over
    # the middle, which is exactly where a head is in a talking-head shot —
    # "top" and "bottom" re-lay the graphic into a band so both fit.
    placement: str = "center"
    placement_fraction: float = 0.42   # share of the frame the band may use

    # Filled in by __post_init__ for a placed graphic: the generators lay out
    # inside `height` (the band) and the frame is composited into a canvas of
    # `canvas_height` at `canvas_offset_y`. Zero means "no band", i.e. centred.
    canvas_height: int = 0
    canvas_offset_y: int = 0

    def __post_init__(self) -> None:
        if self.placement == "center":
            return
        if self.placement not in PLACEMENTS:
            raise GraphicsError(
                f"unknown placement '{self.placement}'. Available: "
                f"{sorted(PLACEMENTS)}")
        full = int(self.height)
        band = max(1, round(full * self.placement_fraction))
        if self.placement == "top":
            offset = 0
        else:
            # Above the caption band, not behind it: a card in the lower third
            # would otherwise be crossed by every subtitle.
            floor = full * (1 - CAPTION_SAFE_BOTTOM) if self.reserve_caption_band else full
            offset = max(0, round(floor - band))
        self.canvas_height = full
        self.canvas_offset_y = offset
        self.height = band
        # The band has already been placed clear of the captions; reserving
        # again inside it would shrink the graphic a second time.
        self.reserve_caption_band = False

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


def _write(draw: ImageDraw.ImageDraw, xy, text: str, font, fill, st: "Style") -> None:
    """Draw text, with the style's contour if it has one.

    Pillow's stroke_width does this natively and correctly handles the glyph
    outline rather than the four-offset trick, which breaks on thin strokes.
    """
    if st.outline and st.outline_width > 0:
        alpha = fill[3] if len(fill) > 3 else 255
        edge = (*st.outline[:3], min(alpha, st.outline[3] if len(st.outline) > 3 else 255))
        # Scale the contour to the glyph. A fixed stroke that reads as a crisp
        # edge on a headline closes up small labels into black blobs, because
        # the stroke grows inward as well as outward.
        size = getattr(font, "size", st.height * 0.05) or st.height * 0.05
        width = max(1, round(st.outline_width * size / (st.height * 0.09)))
        draw.text(xy, text, font=font, fill=fill,
                  stroke_width=width, stroke_fill=edge)
    else:
        draw.text(xy, text, font=font, fill=fill)


def _track(st: "Style", strength: float = 0.22) -> tuple[int, int, int, int]:
    """The colour of an empty meter track, drawn OPAQUE.

    Pillow's ImageDraw replaces pixels rather than blending, so a
    semi-transparent shape drawn over the panel punches a hole in it — on a
    light card the "empty" part of a bar then shows the footage through and
    reads as near-black. Mixing the colour against the panel here and drawing
    it at full alpha keeps the card intact.
    """
    ink = st.muted
    if st.panel:
        base = st.panel[:3]
    else:
        # No card: fall back to a translucent tint, which is correct because
        # there is nothing underneath to punch through.
        return (*ink, int(255 * strength))
    mixed = tuple(round(b + (i - b) * strength) for i, b in zip(ink, base))
    return (*mixed, 255)


def _shape_edge(st: "Style", alpha: int = 255) -> tuple:
    """Contour colour and width for filled shapes, or (None, 0).

    A theme that outlines its text must outline its shapes too: in
    bold_outline the non-accent bars are white, and white on a bright wall is
    the exact failure the contour exists to prevent.
    """
    if not st.outline or st.outline_width <= 0:
        return None, 0
    edge = (*st.outline[:3], min(alpha, st.outline[3] if len(st.outline) > 3 else 255))
    return edge, max(2, round(st.outline_width * 0.7))


def _panel(draw: ImageDraw.ImageDraw, st: "Style", progress: float = 1.0,
           band: tuple[float, float] | None = None) -> None:
    """The backing card, if the theme has one.

    This is what actually makes a light design usable over dark footage and a
    dark one usable over bright footage — the plate, not the palette.
    """
    if not st.panel or progress <= 0:
        return
    inset_x = st.width * st.panel_inset
    inset_y = st.height * st.panel_inset * 0.72
    alpha = int(st.panel[3] * min(1.0, progress)) if len(st.panel) > 3 else 255
    # A card that always fills the frame leaves a short graphic floating in
    # empty space. `band` lets a generator hand over the vertical extent its
    # content actually occupies.
    top, bottom = band if band else (inset_y, st.content_height - inset_y * 0.4)
    draw.rounded_rectangle(
        [inset_x, top, st.width - inset_x, bottom],
        radius=int(st.height * st.panel_radius),
        fill=(*st.panel[:3], alpha))


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


def _hash_unit(n: int) -> float:
    """Deterministic pseudo-random value in [0, 1) from an integer.

    Deliberately not `random`: a render must produce the same file every time,
    or a re-render after an unrelated edit shows a different grain.
    """
    x = (n * 2654435761) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 2246822519) & 0xFFFFFFFF
    x ^= x >> 13
    return x / 0x100000000


def _compose_frame(draw_frame, t: float, style: Style) -> Image.Image:
    img = Image.new("RGBA", (style.width, style.height), (0, 0, 0, 0))
    draw_frame(ImageDraw.Draw(img), t, img)
    if not style.canvas_height or style.canvas_height == style.height:
        return img
    # The generator laid itself out inside the band; put the band where it
    # belongs. Composited rather than scaled: scaling a finished frame to a
    # third of its height would soften every glyph, and a graphic that is
    # slightly blurry reads as a mistake.
    canvas = Image.new("RGBA", (style.width, style.canvas_height), (0, 0, 0, 0))
    canvas.alpha_composite(img, (0, int(style.canvas_offset_y)))
    return canvas


def _average_rgba(samples: list[Image.Image]) -> Image.Image:
    """Average RGBA samples in PREMULTIPLIED space.

    Averaging straight RGB alongside alpha pulls transparent pixels' colour
    (which is arbitrary, usually black) into the result, so every moving edge
    picks up a dark fringe. Premultiplying first weights each sample's colour
    by its own coverage, which is what makes the smear read as motion rather
    than as a dirty outline.
    """
    import numpy as np

    acc_rgb = None
    acc_a = None
    for im in samples:
        arr = np.asarray(im, dtype=np.float32)
        a = arr[..., 3:4] / 255.0
        rgb = arr[..., :3] * a
        acc_rgb = rgb if acc_rgb is None else acc_rgb + rgb
        acc_a = a if acc_a is None else acc_a + a

    n = len(samples)
    mean_rgb = acc_rgb / n
    mean_a = acc_a / n
    # Unpremultiply, guarding the fully transparent pixels.
    safe = np.maximum(mean_a, 1e-6)
    out = np.concatenate([mean_rgb / safe, mean_a * 255.0], axis=-1)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def _render(draw_frame, duration: float, style: Style, out: Path) -> Path:
    total = max(1, int(duration * style.fps))
    samples = max(0, int(style.motion_blur))

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for n in range(total):
            if samples <= 1:
                img = _compose_frame(draw_frame, n / total, style)
            else:
                # Sub-frame offsets centred on the frame time, spanning the
                # open shutter. Centring matters: sampling only forwards drags
                # the whole animation late by half a shutter.
                span = max(0.0, min(1.0, style.shutter)) / total
                shots = []
                for k in range(samples):
                    # Stratified, then jittered within the stratum. Evenly
                    # spaced samples on a fast move leave visible arcs — you can
                    # count them. Jitter turns that banding into noise, which
                    # reads as blur rather than as a stack of copies.
                    # Seeded by frame and sample so renders stay reproducible.
                    jitter = _hash_unit(n * 977 + k) - 0.5
                    frac = (k + 0.5 + jitter) / samples - 0.5
                    t = min(1.0, max(0.0, n / total + frac * span))
                    shots.append(_compose_frame(draw_frame, t, style))
                img = _average_rgba(shots)
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
        _panel(draw, st)
        p = ease_out_cubic(min(1.0, t / move)) if move > 0 else 1.0
        current = value * p
        text = f"{current:,.{decimals}f}".replace(",", ".") + suffix
        w, h = _text_size(draw, text, big)
        x, y = (st.width - w) / 2, st.content_center_y - h / 2
        _write(draw, (x, y), text, font=big, fill=(*st.accent, 255), st=st)
        if label:
            lw, _ = _text_size(draw, label.upper(), small)
            _write(draw, ((st.width - lw) / 2, y + h + st.height * 0.05), label.upper(), font=small, fill=(*st.muted, 255), st=st)
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
        _panel(draw, st)
        elapsed = t * dur
        for i, v in enumerate(values):
            local = (elapsed - i * stagger) / st.reveal
            p = ease_out_cubic(max(0.0, min(1.0, local)))
            if p <= 0:
                continue
            h = max_h * (v / peak) * p
            x0 = left + i * (bar_w + gap)
            colour = st.accent if i == n - 1 else st.accent_2
            edge, ew = _shape_edge(st)
            draw.rounded_rectangle([x0, base_y - h, x0 + bar_w, base_y],
                                   radius=int(bar_w * 0.08), fill=(*colour, 255),
                                   outline=edge, width=ew)
            shown = f"{v * p:,.0f}".replace(",", ".") + suffix
            tw, th = _text_size(draw, shown, value_font)
            _write(draw, (x0 + (bar_w - tw) / 2, base_y - h - th - st.height * 0.025), shown, font=value_font, fill=(*st.text, 255), st=st)
            if labels[i]:
                lw, _ = _text_size(draw, labels[i].upper(), label_font)
                _write(draw, (x0 + (bar_w - lw) / 2, base_y + st.height * 0.022), labels[i].upper(), font=label_font, fill=(*st.muted, 255), st=st)
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
        _panel(draw, st)
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
            _write(draw, (cx - w / 2, cy - h / 2), text, font=big, fill=(*colour, int(255 * prog)), st=st)
            lw, _ = _text_size(draw, label.upper(), small)
            _write(draw, (cx - lw / 2, cy + h * 0.75), label.upper(), font=small, fill=(*st.muted, int(255 * prog)), st=st)

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
        _panel(draw, st)
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
            _write(draw, (tx, bar_y + bar_h * 0.14), title, font=title_font, fill=(*st.text, alpha), st=st)
            if subtitle:
                _write(draw, (tx, bar_y + bar_h * 0.58), subtitle.upper(), font=sub_font, fill=(*st.muted, alpha), st=st)
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
        _panel(draw, st)
        elapsed = t * dur
        shown = max(1, min(len(words), int(elapsed / per) + 1)) if per > 0 else len(words)
        full_w, h = _text_size(draw, text, font)
        x = (st.width - full_w) / 2
        y = st.content_center_y - h / 2
        cursor = x
        for i, w in enumerate(words[:shown]):
            local = ease_out_cubic(max(0.0, min(1.0, (elapsed - i * per) / 0.25)))
            ww, _ = _text_size(draw, w + " ", font)
            _write(draw, (cursor, y + (1 - local) * st.height * 0.02), w, font,
                   (*(st.accent if i == len(words) - 1 else st.text), int(255 * local)), st)
            cursor += ww
    return _render(frame, dur, st, out)


def pie_chart(out: Path, values: list[float], labels: list[str] | None = None,
              style: Style | None = None, duration: float | None = None,
              donut: bool = True, as_percent: bool = True) -> Path:
    """Shares of a whole, swept in clockwise from twelve o'clock.

    Drawn as a donut by default: the hole gives the eye a baseline to compare
    arc lengths against, and leaves room for the total. A full pie is only
    better when there are exactly two slices.

    Segments sweep one after another rather than all at once — the same reason
    the bars stagger. More than six slices stops being readable, so the tail is
    collected into one "Sonstige" wedge instead of being drawn as slivers.
    """
    st = style or Style()
    if not values:
        raise GraphicsError("pie_chart needs at least one value")

    labels = list(labels or [""] * len(values))
    labels += [""] * (len(values) - len(labels))
    values = [max(0.0, float(v)) for v in values]

    MAX_SLICES = 6
    if len(values) > MAX_SLICES:
        head, tail = values[:MAX_SLICES - 1], values[MAX_SLICES - 1:]
        labels = labels[:MAX_SLICES - 1] + ["Sonstige"]
        values = head + [sum(tail)]

    total = sum(values) or 1.0
    dur = duration or (st.reveal + 0.2 * len(values) + st.hold)

    # Palette: the accent leads, the rest step down in weight so the first
    # slice reads as the point being made.
    palette = [st.accent, st.accent_2, (110, 200, 150), (220, 180, 70),
               (170, 130, 220), (130, 140, 150)]

    size = min(st.content_height * 0.66, st.width * 0.34)
    cx, cy = st.width * 0.36, st.content_center_y
    box = [cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2]
    hole = size * 0.56

    label_font = st.font(int(st.height * 0.030))
    value_font = st.font(int(st.height * 0.034))
    total_font = st.font(int(st.height * 0.055))

    # One continuous sweep across the whole ring rather than a stagger per
    # slice. Staggering leaves wedges floating detached from each other
    # mid-animation, which reads as a broken render instead of a build.
    sweep_time = st.reveal + 0.2 * len(values)

    def frame(draw, t, img):
        _panel(draw, st)
        elapsed = t * dur
        swept = 360.0 * ease_out_cubic(max(0.0, min(1.0, elapsed / sweep_time)))
        angle = -90.0
        for i, v in enumerate(values):
            share = 360.0 * (v / total)
            visible = max(0.0, min(share, swept - (angle + 90.0)))
            if visible <= 0:
                break
            edge, ew = _shape_edge(st)
            draw.pieslice(box, angle, angle + visible,
                          fill=(*palette[i % len(palette)], 255),
                          outline=edge, width=ew)
            angle += share

        if donut:
            # Drawing with alpha 0 replaces the pixels rather than blending,
            # which is what punches the hole. On a themed card the hole must
            # show the card, not the footage behind it — punching through the
            # panel makes the ring look like it is floating in a cut-out.
            hole_fill = (*st.panel[:3], st.panel[3] if len(st.panel) > 3 else 255) \
                if st.panel else (0, 0, 0, 0)
            draw.ellipse([cx - hole / 2, cy - hole / 2, cx + hole / 2, cy + hole / 2],
                         fill=hole_fill)
            shown = f"{total:,.0f}".replace(",", ".")
            tw, th = _text_size(draw, shown, total_font)
            _write(draw, (cx - tw / 2, cy - th / 2), shown, font=total_font, fill=(*st.text, 255), st=st)

        # Legend, revealed in step with its slice.
        lx = st.width * 0.60
        row_h = st.height * 0.062
        ly = cy - (len(values) - 1) * row_h / 2
        chip = st.height * 0.022
        reached = -90.0
        for i, v in enumerate(values):
            share = 360.0 * (v / total)
            # Fade a legend row in as its own slice starts being drawn.
            p = max(0.0, min(1.0, (swept - (reached + 90.0)) / max(1.0, share * 0.5)))
            reached += share
            if p <= 0:
                break
            alpha = int(255 * p)
            y = ly + i * row_h
            c_edge, c_ew = _shape_edge(st, alpha)
            draw.rounded_rectangle([lx, y - chip / 2, lx + chip, y + chip / 2],
                                   radius=int(chip * 0.28),
                                   fill=(*palette[i % len(palette)], alpha),
                                   outline=c_edge, width=c_ew)
            text = labels[i] or f"Teil {i + 1}"
            _write(draw, (lx + chip * 1.8, y - _text_size(draw, text, label_font)[1] / 2), text, font=label_font, fill=(*st.text, alpha), st=st)
            share = f"{v / total * 100:.0f}%" if as_percent else f"{v:,.0f}".replace(",", ".")
            sw, sh = _text_size(draw, share, value_font)
            _write(draw, (st.width * 0.92 - sw, y - sh / 2), share, font=value_font, fill=(*st.muted, alpha), st=st)

    return _render(frame, dur, st, out)


# -- icons -------------------------------------------------------------------
#
# Drawn with primitives rather than pulled from an icon font. A font would mean
# another asset to ship, another licence to check, and a missing-glyph failure
# mode that renders as a blank box. These are deliberately few and plain.

def _ico_check(d, x, y, r, c, w):
    d.line([(x - r * .55, y), (x - r * .12, y + r * .45), (x + r * .6, y - r * .5)],
           fill=c, width=w, joint="curve")


def _ico_cross(d, x, y, r, c, w):
    d.line([(x - r * .5, y - r * .5), (x + r * .5, y + r * .5)], fill=c, width=w)
    d.line([(x + r * .5, y - r * .5), (x - r * .5, y + r * .5)], fill=c, width=w)


def _ico_arrow_up(d, x, y, r, c, w):
    d.line([(x, y + r * .6), (x, y - r * .6)], fill=c, width=w)
    d.polygon([(x, y - r * .78), (x - r * .42, y - r * .28), (x + r * .42, y - r * .28)], fill=c)


def _ico_arrow_down(d, x, y, r, c, w):
    d.line([(x, y - r * .6), (x, y + r * .6)], fill=c, width=w)
    d.polygon([(x, y + r * .78), (x - r * .42, y + r * .28), (x + r * .42, y + r * .28)], fill=c)


def _ico_clock(d, x, y, r, c, w):
    d.ellipse([x - r * .7, y - r * .7, x + r * .7, y + r * .7], outline=c, width=w)
    d.line([(x, y), (x, y - r * .42)], fill=c, width=w)
    d.line([(x, y), (x + r * .34, y + r * .16)], fill=c, width=w)


def _ico_person(d, x, y, r, c, w):
    d.ellipse([x - r * .27, y - r * .68, x + r * .27, y - r * .14], fill=c)
    d.pieslice([x - r * .58, y - r * .1, x + r * .58, y + r * .95], 180, 360, fill=c)


def _ico_star(d, x, y, r, c, w):
    import math
    pts = []
    for i in range(10):
        rad = r * (.78 if i % 2 == 0 else .34)
        a = math.radians(-90 + i * 36)
        pts.append((x + rad * math.cos(a), y + rad * math.sin(a)))
    d.polygon(pts, fill=c)


def _ico_bulb(d, x, y, r, c, w):
    d.ellipse([x - r * .48, y - r * .72, x + r * .48, y + r * .24], outline=c, width=w)
    d.line([(x - r * .22, y + r * .38), (x + r * .22, y + r * .38)], fill=c, width=w)
    d.line([(x - r * .15, y + r * .62), (x + r * .15, y + r * .62)], fill=c, width=w)


def _ico_shield(d, x, y, r, c, w):
    d.polygon([(x, y - r * .75), (x + r * .58, y - r * .45), (x + r * .58, y + r * .15),
               (x, y + r * .82), (x - r * .58, y + r * .15), (x - r * .58, y - r * .45)],
              outline=c, width=w)


def _ico_chart(d, x, y, r, c, w):
    for i, h in enumerate((.3, .58, .86)):
        bx = x - r * .55 + i * r * .55
        d.rectangle([bx, y + r * .6 - r * h, bx + r * .3, y + r * .6], fill=c)


def _ico_euro(d, x, y, r, c, w):
    d.arc([x - r * .62, y - r * .68, x + r * .5, y + r * .68], 40, 320, fill=c, width=w)
    d.line([(x - r * .72, y - r * .18), (x + r * .14, y - r * .18)], fill=c, width=w)
    d.line([(x - r * .72, y + r * .16), (x + r * .14, y + r * .16)], fill=c, width=w)


ICONS = {
    "check": _ico_check, "cross": _ico_cross, "up": _ico_arrow_up,
    "down": _ico_arrow_down, "clock": _ico_clock, "person": _ico_person,
    "star": _ico_star, "bulb": _ico_bulb, "shield": _ico_shield,
    "chart": _ico_chart, "euro": _ico_euro,
}


def available_icons() -> list[str]:
    return sorted(ICONS)


def icon_row(out: Path, items: list[tuple[str, str]] | list[str],
             style: Style | None = None, duration: float | None = None,
             circle: bool = True) -> Path:
    """A row of labelled icons, revealed one at a time.

    `items` is [(icon, label), ...] or plain labels, in which case every entry
    gets a check. An unknown icon name raises rather than silently drawing a
    blank — a missing glyph that renders as nothing is the failure mode this
    hand-drawn set exists to avoid.
    """
    st = style or Style()
    if not items:
        raise GraphicsError("icon_row needs at least one item")

    pairs: list[tuple[str, str]] = [
        (i, "") if isinstance(i, str) else (i[0], i[1]) for i in items
    ]
    if all(isinstance(i, str) for i in items):
        pairs = [("check", str(i)) for i in items]

    unknown = [name for name, _ in pairs if name not in ICONS]
    if unknown:
        raise GraphicsError(
            f"unknown icon(s): {unknown}. Available: {available_icons()}")

    MAX_ITEMS = 5
    if len(pairs) > MAX_ITEMS:
        pairs = pairs[:MAX_ITEMS]

    n = len(pairs)
    dur = duration or (0.28 * n + st.hold)
    step = st.width * 0.72 / n
    left = st.width / 2 - step * (n - 1) / 2
    cy = st.content_center_y
    r = min(step * 0.30, st.height * 0.085)
    ring = r * 1.55
    weight = max(3, int(st.height * 0.007))
    label_font = st.font(int(st.height * 0.032))
    stagger = 0.22

    def frame(draw, t, img):
        _panel(draw, st)
        elapsed = t * dur
        for i, (name, label) in enumerate(pairs):
            p = ease_out_cubic(max(0.0, min(1.0, (elapsed - i * stagger) / 0.42)))
            if p <= 0:
                break
            alpha = int(255 * p)
            x = left + i * step
            # Rises slightly into place instead of appearing flat.
            y = cy - (1 - p) * st.height * 0.02
            colour = st.accent if i == n - 1 else st.accent_2

            if circle:
                draw.ellipse([x - ring, y - ring, x + ring, y + ring],
                             outline=(*colour, alpha), width=weight)
            ICONS[name](draw, x, y, r, (*colour, alpha), weight)

            if label:
                lw, _ = _text_size(draw, label, label_font)
                _write(draw, (x - lw / 2, y + ring + st.height * 0.035), label, font=label_font, fill=(*st.text, alpha), st=st)

    return _render(frame, dur, st, out)


def stat_card(out: Path, items: list[tuple[str, str]], style: Style | None = None,
              duration: float | None = None, columns: int = 0) -> Path:
    """A row of figure + label pairs, revealed one at a time.

    Not a chart: the values do not share a scale and are not meant to be
    compared — "26 063 Zeilen" next to "36 Tage" next to "387 Commits". Drawing
    those as bars would invite a comparison that means nothing, which is why
    this exists as its own form.

    `items` is [(value, label), ...]. Four across is the practical limit before
    the figures stop being readable at a glance; more wraps to a second row.
    """
    st = style or Style()
    if not items:
        raise GraphicsError("stat_card needs at least one item")

    pairs = [(str(v), str(l)) for v, l in items]
    n = len(pairs)
    cols = columns or (n if n <= 4 else (n + 1) // 2)
    rows = (n + cols - 1) // cols

    dur = duration or (0.22 * n + st.hold)
    stagger = 0.2

    value_font = st.font(int(st.height * (0.115 if cols <= 3 else 0.085)))
    label_font = st.font(int(st.height * 0.028))

    col_w = st.width * 0.86 / cols
    left = st.width / 2 - col_w * (cols - 1) / 2

    # Lay the block out from its real height rather than dividing the frame:
    # the gap under a figure has to clear the glyphs, not a fraction of their
    # bounding box, or the label lands on top of the number.
    value_size = int(st.height * (0.115 if cols <= 3 else 0.085))
    label_size = int(st.height * 0.028)
    gap = value_size * 0.28
    cell_h = value_size + gap + label_size
    block_h = rows * cell_h + (rows - 1) * value_size * 0.5
    block_top = st.content_center_y - block_h / 2
    pad = st.height * 0.075

    def frame(draw, t, img):
        _panel(draw, st, band=(block_top - pad, block_top + block_h + pad))
        elapsed = t * dur
        for idx, (value, label) in enumerate(pairs):
            p = ease_out_cubic(max(0.0, min(1.0, (elapsed - idx * stagger) / 0.45)))
            if p <= 0:
                break
            alpha = int(255 * p)
            r, c = divmod(idx, cols)
            cx = left + c * col_w
            top = block_top + r * (cell_h + value_size * 0.5) \
                - (1 - p) * st.height * 0.015

            vw, _ = _text_size(draw, value, value_font)
            _write(draw, (cx - vw / 2, top), value, value_font,
                   (*st.accent, alpha), st)
            lw, _ = _text_size(draw, label.upper(), label_font)
            _write(draw, (cx - lw / 2, top + value_size + gap), label.upper(),
                   label_font, (*st.muted, alpha), st)

    return _render(frame, dur, st, out)


def bar_chart_h(out: Path, items: list[tuple[str, float]], style: Style | None = None,
                duration: float | None = None, suffix: str = "",
                decimals: int | None = None) -> Path:
    """Horizontal bars with the label beside each one.

    Vertical bars need short labels and few of them. Once there are ten
    categories with names like "BLUMENBEET" the labels either overlap or turn
    sideways, and a sideways label is a label nobody reads. Horizontal solves
    both: the name sits on its own line, and adding a row costs height rather
    than squeezing width.
    """
    st = style or Style()
    if not items:
        raise GraphicsError("bar_chart_h needs at least one item")

    rows = [(str(k), float(v)) for k, v in items]
    peak = max(v for _, v in rows) or 1.0
    n = len(rows)

    dur = duration or (st.reveal + 0.1 * n + st.hold)
    stagger = min(0.14, 1.2 / n)

    label_font = st.font(int(st.height * min(0.036, 0.52 / n)))
    value_font = st.font(int(st.height * min(0.036, 0.52 / n)))

    top = st.content_height * 0.10
    usable = st.content_height * 0.80
    row_h = usable / n
    bar_h = row_h * 0.62

    label_w = st.width * 0.22
    track_x = st.width * 0.26
    track_w = st.width * 0.56

    def frame(draw, t, img):
        _panel(draw, st)
        elapsed = t * dur
        for i, (label, value) in enumerate(rows):
            p = ease_out_cubic(max(0.0, min(1.0, (elapsed - i * stagger) / st.reveal)))
            if p <= 0:
                break
            alpha = int(255 * p)
            y = top + i * row_h + (row_h - bar_h) / 2
            # First row leads in the accent; the rest step back so the eye
            # starts where the point is.
            colour = st.accent if i == 0 else st.accent_2

            lw, lh = _text_size(draw, label.upper(), label_font)
            _write(draw, (track_x - lw - st.width * 0.02, y + (bar_h - lh) / 2),
                   label.upper(), label_font, (*st.text, alpha), st)

            width = track_w * (value / peak) * p
            edge, ew = _shape_edge(st, alpha)
            if width > 1:
                draw.rounded_rectangle([track_x, y, track_x + width, y + bar_h],
                                       radius=int(bar_h * 0.28),
                                       fill=(*colour, alpha), outline=edge, width=ew)

            # Per row, not per chart: "52 %" alongside "12,4 %" reads better
            # than forcing every whole number to carry a pointless ",0".
            dp = decimals if decimals is not None else (0 if float(value).is_integer() else 1)
            shown = (f"{value * p:,.{dp}f}"
                     .replace(",", "X").replace(".", ",").replace("X", ".")) + suffix
            vw, vh = _text_size(draw, shown, value_font)
            _write(draw, (track_x + width + st.width * 0.012, y + (bar_h - vh) / 2),
                   shown, value_font, (*st.muted, alpha), st)

    return _render(frame, dur, st, out)


def linked_meters(out: Path, control: str, meters: list[tuple[str, float, float, str]],
                  style: Style | None = None, duration: float | None = None,
                  sweeps: int = 2) -> Path:
    """One control, several readouts that move together.

    Built for the case where a diagram has to show *coupling* rather than
    values: two quantities driven by the same input, so the viewer sees that
    one cannot be raised without the other. A pair of static bars cannot say
    that; the shared handle can.

    `meters` is [(label, base, factor, unit), ...] — each readout is
    `base + factor * control`, which is how the underlying formula is usually
    written down. The control sweeps 0 -> 1 -> 0 so the coupling is visible in
    both directions; a single sweep reads as two bars that happen to grow.
    """
    st = style or Style()
    if not meters:
        raise GraphicsError("linked_meters needs at least one meter")

    dur = duration or (2.2 * sweeps + st.hold)
    rows = [(str(la), float(b), float(f), str(u)) for la, b, f, u in meters]
    # Normalise against the largest value the meter actually reaches, not
    # against base + factor: a negative factor is the interesting case (one
    # quantity bought with the other), and there the peak is at charge 0.
    peak = [max(b, b + f) for _, b, f, _ in rows]
    for (label, *_), top_value in zip(rows, peak):
        if top_value <= 0:
            raise GraphicsError(f"meter {label!r} never reaches a positive value")

    title_font = st.font(int(st.height * 0.030))
    label_font = st.font(int(st.height * 0.032))
    value_font = st.font(int(st.height * 0.042))

    track_x = st.width * 0.30
    track_w = st.width * 0.50
    handle_r = st.height * 0.020

    row_h = st.content_height * 0.20
    bar_h = row_h * 0.42
    # The control sits one row above the first readout, so the block is
    # (len(rows) + 1) rows tall and `top` is the control's centre.
    top = (st.content_height - row_h * len(rows)) / 2

    # Hug the rows. A card sized to the frame leaves a two-meter diagram
    # floating in a sea of empty plate, which is what the first version did.
    pad = row_h * 0.55
    band = (top - pad, top + row_h * len(rows) + pad)

    def frame(draw, t, img):
        _panel(draw, st, band=band)
        elapsed = t * dur
        active = min(1.0, elapsed / (dur - st.hold)) if dur > st.hold else 1.0
        # Triangle wave: up and back down, `sweeps` times, then hold at full.
        if elapsed >= dur - st.hold:
            charge = 1.0
        else:
            phase = (active * sweeps) % 1.0
            charge = ease_in_out_cubic(phase * 2 if phase < 0.5 else (1 - phase) * 2)

        # -- the control -------------------------------------------------
        cy = top
        lw, lh = _text_size(draw, control.upper(), title_font)
        _write(draw, (track_x - lw - st.width * 0.03, cy - lh / 2),
               control.upper(), title_font, (*st.text, 255), st)

        edge, ew = _shape_edge(st)
        draw.rounded_rectangle(
            [track_x, cy - handle_r * 0.32, track_x + track_w, cy + handle_r * 0.32],
            radius=int(handle_r * 0.32), fill=_track(st, 0.30))
        hx = track_x + track_w * charge
        draw.rounded_rectangle(
            [track_x, cy - handle_r * 0.32, hx, cy + handle_r * 0.32],
            radius=int(handle_r * 0.32), fill=(*st.accent, 255))
        draw.ellipse([hx - handle_r, cy - handle_r, hx + handle_r, cy + handle_r],
                     fill=(*st.accent, 255), outline=edge, width=ew)

        # -- the readouts ------------------------------------------------
        for i, (label, base, factor, unit) in enumerate(rows):
            value = base + factor * charge
            y = top + row_h * (i + 1)

            lw, lh = _text_size(draw, label.upper(), label_font)
            _write(draw, (track_x - lw - st.width * 0.03, y - lh / 2),
                   label.upper(), label_font, (*st.text, 255), st)

            draw.rounded_rectangle(
                [track_x, y - bar_h / 2, track_x + track_w, y + bar_h / 2],
                radius=int(bar_h * 0.28), fill=_track(st))
            width = track_w * max(0.0, value / peak[i])
            colour = st.accent if i == 0 else st.accent_2
            draw.rounded_rectangle(
                [track_x, y - bar_h / 2, track_x + width, y + bar_h / 2],
                radius=int(bar_h * 0.28), fill=(*colour, 255),
                outline=edge, width=ew)

            shown = f"{value:,.1f}".replace(".", ",") + (f" {unit}" if unit else "")
            vw, vh = _text_size(draw, shown, value_font)
            _write(draw, (track_x + track_w + st.width * 0.018, y - vh / 2),
                   shown, value_font, (*st.muted, 255), st)

    return _render(frame, dur, st, out)


THEMES: dict[str, dict] = {
    # The original: assumes dark or busy footage, no plate.
    "dark_minimal": {
        "accent": (255, 90, 0), "accent_2": (90, 170, 255),
        "text": (255, 255, 255), "muted": (150, 150, 150),
        "outline": None, "outline_width": 0, "panel": None,
    },
    # The common YouTube look: a bright card with dark type. Readable over any
    # footage because the card, not the palette, does the work.
    "light_card": {
        "accent": (232, 93, 4), "accent_2": (0, 119, 182),
        "text": (24, 28, 33), "muted": (108, 117, 125),
        "outline": None, "outline_width": 0,
        "panel": (250, 249, 246, 242), "panel_radius": 0.024, "panel_inset": 0.07,
    },
    # No plate, heavy contour. Survives on anything and reads as the
    # high-contrast style short-form has settled on.
    "bold_outline": {
        "accent": (255, 214, 0), "accent_2": (34, 87, 214),
        "text": (255, 255, 255), "muted": (240, 240, 240),
        "outline": (12, 12, 12, 255), "outline_width": 6, "panel": None,
    },
    # Softer corporate register: pale card, muted blues, thin type.
    "soft_light": {
        "accent": (13, 110, 168), "accent_2": (108, 168, 204),
        "text": (33, 41, 49), "muted": (124, 137, 148),
        "outline": None, "outline_width": 0,
        "panel": (255, 255, 255, 226), "panel_radius": 0.03, "panel_inset": 0.08,
    },
}


# Sample counts, not raw numbers, so the UI and the chat speak the same
# language. Below ~12 the strata are still countable as arcs on a fast move;
# above ~16 the cost stops buying visible smoothness.
MOTION_BLUR_LEVELS = {"off": 0, "light": 8, "normal": 16, "heavy": 24}


def available_motion_blur() -> list[str]:
    return list(MOTION_BLUR_LEVELS)


def available_themes() -> list[str]:
    return sorted(THEMES)


def make_style(theme: str = "dark_minimal", **overrides) -> Style:
    """Build a Style from a named theme.

    An unknown name raises rather than silently falling back: a graphic
    rendered in the wrong theme is worse than a render that stops and says so.
    """
    if theme not in THEMES:
        raise GraphicsError(
            f"unknown theme '{theme}'. Available: {available_themes()}")
    return Style(**{**THEMES[theme], **overrides})


GENERATORS = {
    "number_animation": number_animation,
    "bar_chart": bar_chart,
    "comparison": comparison,
    "lower_third": lower_third,
    "text_animation": text_animation,
    "pie_chart": pie_chart,
    "icon_row": icon_row,
    "stat_card": stat_card,
    "bar_chart_h": bar_chart_h,
    "linked_meters": linked_meters,
}


def available_placements() -> list[str]:
    """Where a graphic may sit. Not cosmetic: a centred full-width card lands
    on the speaker's face, so this is what makes "face plus card" possible."""
    return list(PLACEMENTS)


def available_kinds() -> list[str]:
    """Only what is actually implemented is offered — no dead menu entries."""
    return sorted(GENERATORS)
