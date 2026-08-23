"""ffprobe facts and proxy generation.

Everything downstream needs to know the real shape of the source: frame rate,
duration, whether there is an audio track at all, and whether the footage is
HDR. Guessing any of these produces output that looks fine locally and wrong
after upload.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

# iPhone defaults to HLG HDR; many mirrorless cameras ship PQ. Downconverting
# bit depth without tone-mapping leaves 8-bit values carrying HDR metadata,
# which players interpret as blown-out. Detect so the render can fix it.
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mts", ".m2ts"}


@dataclass
class MediaInfo:
    path: str
    duration: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    has_video: bool = False
    has_audio: bool = False
    is_hdr: bool = False
    is_portrait: bool = False
    video_codec: str = ""
    audio_codec: str = ""
    size_bytes: int = 0

    @property
    def aspect(self) -> str:
        if not self.width or not self.height:
            return "unknown"
        r = self.width / self.height
        for label, target in (("16:9", 16 / 9), ("9:16", 9 / 16), ("1:1", 1.0), ("4:5", 0.8)):
            if abs(r - target) < 0.02:
                return label
        return f"{r:.2f}:1"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["aspect"] = self.aspect
        return d


class MediaError(RuntimeError):
    """ffprobe could not read the file — corrupt, unsupported, or not media."""


def probe(path: Path) -> MediaInfo:
    path = Path(path)
    if not path.exists():
        raise MediaError(f"file not found: {path}")

    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise MediaError(
            f"ffprobe could not read {path.name}. "
            "The file may be corrupt or not a media file."
        )

    data = json.loads(proc.stdout)
    info = MediaInfo(path=str(path))
    info.size_bytes = path.stat().st_size

    try:
        info.duration = float(data.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        info.duration = 0.0

    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        if kind == "video" and not info.has_video:
            info.has_video = True
            info.video_codec = stream.get("codec_name", "")
            info.width = int(stream.get("width") or 0)
            info.height = int(stream.get("height") or 0)
            info.is_hdr = stream.get("color_transfer") in HDR_TRANSFERS
            info.fps = _parse_rate(stream.get("avg_frame_rate")) or \
                _parse_rate(stream.get("r_frame_rate")) or 0.0
        elif kind == "audio" and not info.has_audio:
            info.has_audio = True
            info.audio_codec = stream.get("codec_name", "")

    info.is_portrait = info.height > info.width > 0
    return info


def _parse_rate(raw: str | None) -> float:
    if not raw:
        return 0.0
    num, _, den = raw.partition("/")
    try:
        value = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return value if value > 0 else 0.0


def build_proxy(source: Path, dest: Path, height: int = 540, fps: int = 30) -> Path:
    """A small, seek-friendly copy for the preview player and for analysis.

    Scrubbing a 4K source in a browser is unusable and re-decoding it for every
    analysis pass is wasteful. The proxy is generated once and reused.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest

    cmd = [
        "ffmpeg", "-y", "-i", str(source),
        "-vf", f"scale=-2:{height}",
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not dest.exists():
        raise MediaError(f"proxy generation failed: {proc.stderr[-400:]}")
    return dest


def extract_thumbnail(source: Path, dest: Path, at: float = 1.0, width: int = 480) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at), "-i", str(source),
         "-frames:v", "1", "-vf", f"scale={width}:-2", str(dest)],
        capture_output=True, text=True,
    )
    return dest
