"""The chat works with no model installed."""
from __future__ import annotations

import pytest

from engine.llm import parse_command


@pytest.mark.parametrize("text,expected,arg", [
    ("Entferne die ersten 5 Sekunden", "trim_start", "5"),
    ("entferne die letzten 2.5 sekunden", "trim_end", "2.5"),
    ("Remove the first 10 seconds", "trim_start", "10"),
    ("Mach die Captions größer", "caption_size", "größer"),
    ("Entferne alle Grafiken", "remove_overlays", ""),
    ("Mach das Video in 9:16", "aspect", "9:16"),
    ("Erstelle einen 30 Sekunden Short", "make_short", "30"),
    ("Setz den Grade auf warm_cinematic", "grade", "warm_cinematic"),
])
def test_recognised_commands(text, expected, arg):
    cmd = parse_command(text)
    assert cmd and cmd["command"] == expected and cmd["arg"] == arg


def test_unrecognised_input_returns_none_rather_than_guessing():
    # Guessing an edit from an unclear sentence is worse than admitting it.
    assert parse_command("Was ist der Sinn des Lebens?") is None


def test_decimal_comma_is_normalised():
    assert parse_command("entferne die ersten 1,5 sekunden")["arg"] == "1.5"
