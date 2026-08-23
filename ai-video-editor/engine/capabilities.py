"""What this machine can actually do — probed once, cached, reported honestly.

Every stage of the pipeline asks this module whether its dependency exists
before claiming it can run. A stage whose tool is missing reports
`unavailable` with a fix, never a silent success. That is the difference
between a pipeline you can trust and one that quietly skips work.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, asdict, field
from functools import lru_cache


@dataclass
class Tool:
    name: str
    available: bool
    version: str = ""
    hint: str = ""          # how to install it, shown in the UI
    optional: bool = True   # False => the app cannot run at all


@dataclass
class Hardware:
    cpu_count: int = 0
    ram_gb: float = 0.0
    gpu: str = ""
    vram_gb: float = 0.0
    cuda: bool = False


@dataclass
class Capabilities:
    tools: dict[str, Tool] = field(default_factory=dict)
    hardware: Hardware = field(default_factory=Hardware)

    def has(self, name: str) -> bool:
        t = self.tools.get(name)
        return bool(t and t.available)

    def missing_required(self) -> list[Tool]:
        return [t for t in self.tools.values() if not t.available and not t.optional]

    def to_dict(self) -> dict:
        return {
            "tools": {k: asdict(v) for k, v in self.tools.items()},
            "hardware": asdict(self.hardware),
        }


def _run(cmd: list[str], timeout: int = 15) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout or p.stderr).strip()
    except Exception:
        return False, ""


def _binary(name: str, version_args: list[str], hint: str, optional: bool = True) -> Tool:
    path = shutil.which(name)
    if not path:
        return Tool(name=name, available=False, hint=hint, optional=optional)
    ok, out = _run([path, *version_args])
    version = out.splitlines()[0][:120] if ok and out else ""
    return Tool(name=name, available=True, version=version, hint=hint, optional=optional)


def _module(name: str, import_name: str, hint: str) -> Tool:
    try:
        mod = __import__(import_name)
        return Tool(name=name, available=True,
                    version=str(getattr(mod, "__version__", "")), hint=hint)
    except Exception:
        return Tool(name=name, available=False, hint=hint)


def _hardware() -> Hardware:
    hw = Hardware()

    try:
        import os
        hw.cpu_count = os.cpu_count() or 0
    except Exception:
        pass

    # RAM without a hard psutil dependency.
    try:
        import os
        hw.ram_gb = round(
            os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3), 1
        )
    except Exception:
        try:
            import psutil
            hw.ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        except Exception:
            pass

    ok, out = _run(["nvidia-smi",
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits"])
    if ok and out:
        first = out.splitlines()[0]
        parts = [p.strip() for p in first.split(",")]
        if len(parts) >= 2:
            hw.gpu = parts[0]
            try:
                hw.vram_gb = round(float(parts[1]) / 1024, 1)
            except ValueError:
                pass
            hw.cuda = True

    if not hw.cuda:
        try:
            import torch
            if torch.cuda.is_available():
                hw.cuda = True
                hw.gpu = torch.cuda.get_device_name(0)
                hw.vram_gb = round(
                    torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 1)
        except Exception:
            pass

    return hw


@lru_cache(maxsize=1)
def detect() -> Capabilities:
    """Probe once per process. Call detect.cache_clear() after installing something."""
    tools = {
        "ffmpeg": _binary(
            "ffmpeg", ["-version"],
            "Required. macOS: brew install ffmpeg · Debian: apt install ffmpeg "
            "· Windows: winget install Gyan.FFmpeg",
            optional=False),
        "ffprobe": _binary(
            "ffprobe", ["-version"],
            "Ships with ffmpeg. If ffmpeg works but ffprobe does not, the install is partial.",
            optional=False),
        "auto-editor": _binary(
            "auto-editor", ["--version"],
            "Silence detection. pip install auto-editor"),
        "scenedetect": _module(
            "scenedetect", "scenedetect",
            "Scene detection. pip install scenedetect[opencv]"),
        "whisperx": _module(
            "whisperx", "whisperx",
            "Local transcription. pip install whisperx (large; pulls in torch)"),
        "ollama": _binary(
            "ollama", ["--version"],
            "Local LLM for the chat and creative suggestions. https://ollama.com"),
    }
    return Capabilities(tools=tools, hardware=_hardware())


def quality_profile() -> dict:
    """Scale work to the machine instead of failing on a small one."""
    caps = detect()
    hw = caps.hardware

    if hw.cuda and hw.vram_gb >= 10:
        return {"whisper_model": "large-v3", "device": "cuda", "compute_type": "float16",
                "batch_size": 16, "encoder": "h264_nvenc", "proxy_height": 720}
    if hw.cuda and hw.vram_gb >= 5:
        return {"whisper_model": "medium", "device": "cuda", "compute_type": "float16",
                "batch_size": 8, "encoder": "h264_nvenc", "proxy_height": 540}
    if hw.ram_gb >= 16:
        return {"whisper_model": "small", "device": "cpu", "compute_type": "int8",
                "batch_size": 4, "encoder": "libx264", "proxy_height": 540}
    return {"whisper_model": "base", "device": "cpu", "compute_type": "int8",
            "batch_size": 1, "encoder": "libx264", "proxy_height": 360}


if __name__ == "__main__":
    import json
    caps = detect()
    print(json.dumps(caps.to_dict(), indent=2))
    print("\nprofile:", json.dumps(quality_profile(), indent=2))
