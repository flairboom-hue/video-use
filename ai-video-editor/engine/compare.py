"""Before/after comparisons from two stills or two clips.

A devlog spends most of its time saying "this was broken, then I fixed it",
and that sentence is worth nothing without the picture. Two shots side by side
is the obvious layout and the weak one: the eye has to travel between them and
hold the first in memory, so small differences — a texture that is too bright,
a shadow that is missing — simply do not register.

A wipe puts both states in the SAME screen position. The divider moves, the
frame does not, so the difference appears exactly where the viewer is already
looking. That is the whole reason this module exists rather than an ffmpeg
one-liner with `hstack`.

Stills and clips are both accepted, because most "before" states only exist as
a screenshot someone took at the time.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from . import graphics as gfx
from . import media

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# The badge sits in a corner rather than over the middle: the middle is where
# the difference is, and a label covering it defeats the point.
BADGE_MARGIN = 0.035
BADGE_FADE = 0.30
DIVIDER_FADE = 0.15


class CompareError(RuntimeError):
    pass


@dataclass
class CompareSpec:
    """Timing of the wipe.

    The two holds are not padding. Without the opening hold the viewer never
    sees the "before" state cleanly, and without the closing one the wipe
    finishes and cuts away before the fixed version has registered.
    """
    hold_before: float = 0.8
    sweep: float = 1.6
    hold_after: float = 1.4

    @property
    def duration(self) -> float:
        return self.hold_before + self.sweep + self.hold_after

    def validate(self) -> None:
        if self.sweep <= 0:
            raise CompareError("the sweep needs a positive duration")
        if self.hold_before < 0 or self.hold_after < 0:
            raise CompareError("holds cannot be negative")


def is_image(path: Path) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def _input_args(path: Path, duration: float) -> list[str]:
    """Read `duration` seconds from a file, whether it is a still or a clip.

    A still has no duration of its own and a clip may be shorter than the
    comparison, so both are looped and cut to length. Without this a clip one
    second long ends the whole wipe one second in.
    """
    if is_image(path):
        return ["-loop", "1", "-t", f"{duration:.3f}", "-i", str(path)]
    return ["-stream_loop", "-1", "-t", f"{duration:.3f}", "-i", str(path)]


def _badge(out: Path, text: str, side: str, st: gfx.Style) -> Path:
    """One corner label, drawn once as a still.

    Separate files per side because each one appears and leaves at a different
    moment: a label only tells the truth while its own state is on screen.
    """
    img = Image.new("RGBA", (st.width, st.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = st.font(max(14, int(st.height * 0.030)))
    pad_x = st.height * 0.020
    pad_y = st.height * 0.012
    margin = st.height * BADGE_MARGIN

    label = text.upper()
    tw, th = gfx._text_size(draw, label, font)
    box_w, box_h = tw + pad_x * 2, th + pad_y * 2
    x = margin if side == "left" else st.width - margin - box_w
    draw.rounded_rectangle([x, margin, x + box_w, margin + box_h],
                           radius=st.height * 0.010,
                           fill=st.panel or (0, 0, 0, 190))
    gfx._write(draw, (x + pad_x, margin + pad_y), label, font, (*st.text, 255), st)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def _divider(out: Path, st: gfx.Style) -> Path:
    """The moving seam marker, drawn once as a tall strip.

    Not drawbox: its geometry expressions are evaluated once on this build, so
    a t-dependent x parks the line at one edge for the whole clip. overlay
    re-evaluates x every frame, which is what a moving divider needs.
    """
    line = max(2, round(st.width * 0.0022))
    halo = line + 2 * max(2, round(st.width * 0.0016))
    img = Image.new("RGBA", (halo, st.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # A dark halo under a bright line, so the seam stays visible over footage
    # that happens to match the accent colour on one side.
    draw.rectangle([0, 0, halo - 1, st.height - 1], fill=(0, 0, 0, 140))
    left = (halo - line) // 2
    draw.rectangle([left, 0, left + line - 1, st.height - 1], fill=(*st.accent, 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def split_expr(spec: CompareSpec, width_var: str, time_var: str) -> str:
    """Where the divider is at a given moment, as an ffmpeg expression.

    Clamped at both ends so the holds are still, and written once here because
    the blend and the divider line must agree to the pixel — two copies of this
    formula drifting apart would draw the line beside the seam.
    """
    # The new state sweeps in from the right, so the seam runs 1 -> 0. That
    # direction is what puts "vorher" on the left, in reading order.
    return (f"{width_var}*(1-clip(({time_var}-{spec.hold_before:.3f})"
            f"/{spec.sweep:.3f},0,1))")


def build_comparison(before: Path, after: Path, out: Path,
                     label_before: str = "vorher", label_after: str = "nachher",
                     style: gfx.Style | None = None,
                     spec: CompareSpec | None = None) -> Path:
    """Render the wipe. Returns `out`.

    Both inputs are fitted to the same frame before they are blended: a wipe
    between two differently sized shots would shift the content across the
    divider, which reads as a camera move rather than a change.
    """
    before, after, out = Path(before), Path(after), Path(out)
    for path, role in ((before, "before"), (after, "after")):
        if not path.exists():
            raise CompareError(f"{role} file not found: {path}")

    st = style or gfx.Style()
    spec = spec or CompareSpec()
    spec.validate()
    dur = spec.duration

    for path, role in ((before, "before"), (after, "after")):
        if is_image(path):
            continue
        info = media.probe(path)
        if not info.has_video:
            raise CompareError(f"{role} file has no video stream: {path.name}")

    out.parent.mkdir(parents=True, exist_ok=True)
    badges: list[tuple[Path, str]] = []
    for text, side in ((label_before, "left"), (label_after, "right")):
        if not text:
            continue
        path = out.parent / f".{out.stem}_{side}.png"
        badges.append((_badge(path, text, side, st), side))

    # format=gbrp because chroma is subsampled in yuv, so a hard vertical seam
    # lands on a colour boundary half a pixel wide and fringes. Wiping in
    # planar RGB keeps the divider clean; the conversion back happens once.
    fit = (f"scale={st.width}:{st.height}:force_original_aspect_ratio=decrease,"
           f"pad={st.width}:{st.height}:(ow-iw)/2:(oh-ih)/2:color=black,"
           f"setsar=1,fps={st.fps},format=gbrp")

    divider = _divider(out.parent / f".{out.stem}_divider.png", st)
    scratch = [divider] + [p for p, _ in badges]

    # xfade rather than a per-pixel blend expression. Both draw the same hard
    # seam, but blend evaluates an expression for every pixel of every frame:
    # measured on a 3.8s 1080p pair, 24.6s against 4.3s.
    #
    # wipeleft, not wiperight: it brings the second input in from the right,
    # which is what leaves "vorher" on the left where a reader expects it.
    graph = [
        f"[0:v]{fit}[b]",
        f"[1:v]{fit}[a]",
        f"[b][a]xfade=transition=wipeleft:duration={spec.sweep:.3f}:"
        f"offset={spec.hold_before:.3f}[w]",
        # The divider belongs to the movement. Left on screen through the
        # holds it is a stray orange line parked against an edge.
        f"[2:v]format=rgba,"
        f"fade=t=in:st={spec.hold_before - DIVIDER_FADE:.3f}:d={DIVIDER_FADE}:alpha=1,"
        f"fade=t=out:st={spec.hold_before + spec.sweep:.3f}:d={DIVIDER_FADE}:alpha=1[dv]",
        f"[w][dv]overlay=x='{split_expr(spec, 'W', 't')}-w/2':y=0:"
        f"format=auto[v0]",
    ]

    # A label is only true while its own side is on screen. "Vorher" leaves as
    # the wipe completes; "nachher" arrives as it starts.
    stage = "v0"
    for i, (_, side) in enumerate(badges):
        idx = 3 + i
        if side == "left":
            fade = f"fade=t=out:st={spec.hold_before + spec.sweep - BADGE_FADE:.3f}:d={BADGE_FADE}:alpha=1"
        else:
            fade = f"fade=t=in:st={spec.hold_before:.3f}:d={BADGE_FADE}:alpha=1"
        graph.append(f"[{idx}:v]format=rgba,{fade}[lb{i}]")
        graph.append(f"[{stage}][lb{i}]overlay=0:0:format=auto[v{i + 1}]")
        stage = f"v{i + 1}"
    graph.append(f"[{stage}]format=yuv420p[v]")

    # Each side has to survive its own hold AND the sweep it shares. Cut the
    # "before" at its hold and xfade has nothing left to wipe away: the clip
    # comes out short and entirely in the "after" state, with no wipe at all
    # and no error. Longer than this is merely decoded and thrown away.
    cmd = ["ffmpeg", "-y"]
    cmd += _input_args(before, spec.hold_before + spec.sweep)
    cmd += _input_args(after, spec.sweep + spec.hold_after)
    cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(divider)]
    for path, _ in badges:
        cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(path)]
    cmd += ["-filter_complex", ";".join(graph), "-map", "[v]", "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(st.fps),
            "-t", f"{dur:.3f}", str(out)]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    for path in scratch:
        path.unlink(missing_ok=True)
    if proc.returncode != 0 or not out.exists():
        raise CompareError(f"comparison render failed: {proc.stderr[-500:]}")
    return out
