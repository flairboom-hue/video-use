"""Swappable LLM interface — local first, cloud optional, neither required.

The pipeline must work with no model at all, so every consumer of this module
handles `Unavailable` as a normal outcome. The chat falls back to a
deterministic command parser that covers the common instructions; the LLM only
widens what can be phrased, it is never load-bearing.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass


class Unavailable(RuntimeError):
    pass


@dataclass
class Provider:
    name: str
    model: str
    endpoint: str = ""
    api_key: str = ""


def configured() -> Provider:
    backend = os.environ.get("LLM_BACKEND", "ollama").lower()
    if backend == "ollama":
        return Provider("ollama", os.environ.get("OLLAMA_MODEL", "llama3.1"),
                        os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    if backend in {"openai", "openai-compatible"}:
        return Provider("openai", os.environ.get("LLM_MODEL", "gpt-4o-mini"),
                        os.environ.get("LLM_ENDPOINT", "https://api.openai.com/v1"),
                        os.environ.get("LLM_API_KEY", ""))
    return Provider("none", "")


def available() -> bool:
    p = configured()
    if p.name == "ollama":
        try:
            with urllib.request.urlopen(f"{p.endpoint}/api/tags", timeout=1.5):
                return True
        except Exception:
            return False
    return p.name == "openai" and bool(p.api_key)


def complete(prompt: str, system: str = "", timeout: int = 60) -> str:
    p = configured()
    if p.name == "ollama":
        body = json.dumps({
            "model": p.model, "prompt": prompt, "system": system, "stream": False,
        }).encode()
        req = urllib.request.Request(f"{p.endpoint}/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())["response"]
        except Exception as exc:
            raise Unavailable(
                f"Ollama at {p.endpoint} did not answer ({exc}). "
                "Start it with `ollama serve` and pull a model, "
                f"e.g. `ollama pull {p.model}`.") from exc

    if p.name == "openai":
        if not p.api_key:
            raise Unavailable("LLM_API_KEY is not set.")
        body = json.dumps({
            "model": p.model,
            "messages": ([{"role": "system", "content": system}] if system else [])
                        + [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            f"{p.endpoint}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {p.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            raise Unavailable(f"LLM request failed: {exc.code}") from exc

    raise Unavailable("No LLM configured. Set LLM_BACKEND=ollama and run `ollama serve`.")


# ------------------------------------------------------- deterministic chat ---
#
# These patterns run BEFORE any model. They cover the instructions users
# actually repeat, they are testable, and they cannot hallucinate a timestamp.

COMMANDS = [
    ("trim_start",   r"(?:entferne|schneide|cut|remove)\D*(?:die\s+)?(?:ersten|first)\s+(\d+(?:[.,]\d+)?)\s*(?:sekunden|seconds|s)\b"),
    ("trim_end",     r"(?:entferne|schneide|cut|remove)\D*(?:die\s+)?(?:letzten|last)\s+(\d+(?:[.,]\d+)?)\s*(?:sekunden|seconds|s)\b"),
    ("caption_size", r"(?:captions?|untertitel)\D*(gr[oö]ßer|kleiner|bigger|smaller)"),
    ("caption_style", r"(?:caption|untertitel)(?:stil|style)?\D*(bold_center|word_highlight|clean_lower|big_impact)"),
    ("remove_overlays", r"(?:entferne|remove)\s+(?:alle\s+)?(?:grafiken|overlays|animationen|graphics)"),
    ("aspect",       r"\b(9:16|16:9|1:1|4:5)\b"),
    ("make_short",   r"(\d+)\s*[-\s]?(?:sekunden|second)s?\s*(?:short|clip|reel)"),
    ("grade",        r"\b(warm_cinematic|neutral|punch|flat)\b"),
    ("theme",        r"\b(light_card|dark_minimal|bold_outline|soft_light)\b"),
]


def parse_command(text: str) -> dict | None:
    """Map a sentence onto a concrete project mutation, or return None."""
    low = text.lower().strip()
    for name, pattern in COMMANDS:
        m = re.search(pattern, low)
        if not m:
            continue
        arg = m.group(1) if m.groups() else ""
        return {"command": name, "arg": arg.replace(",", "."), "matched": m.group(0)}
    return None
