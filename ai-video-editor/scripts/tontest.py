#!/usr/bin/env python3
"""Prüft an einer Probeaufnahme, ob der Raum den Rohschnitt überhaupt zulässt.

Der ganze automatische Schnitt hängt an einer einzigen Annahme: dass Pausen
leiser sind als Sprache. In einem Raum mit Lüfter, Straße oder Rechnerrauschen
stimmt das nicht mehr — auto-editor findet dann keine Stille, der Rohschnitt
entfernt nichts, und das merkst du sonst erst nach vierzig Minuten Aufnahme.

Also: sechzig Sekunden sprechen wie im Video, mit echten Pausen zwischen den
Sätzen, und das hier laufen lassen.

    python scripts/tontest.py probe.mp4

Kein Urteil über Klang, Stimme oder Mikrofon — nur über die eine Frage, die
das Werkzeug beantworten kann: sind die Pausen als Pausen erkennbar?
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import media, rough_cut  # noqa: E402

# Sprache mit echten Satzpausen liegt erfahrungsgemäß bei 15-40 % Stille. Viel
# weniger heißt: der Raum ist zu laut. Viel mehr heißt: sehr lange Pausen —
# nicht falsch, aber es lohnt sich hinzuschauen, ob das Absicht war.
ZU_WENIG = 8.0
VIEL = 55.0

# Unter 400 ms gilt ein Schnipsel als Atmer und fliegt raus (MIN_CLIP). Bleiben
# im Schnitt sehr kurze Segmente übrig, wird zerhackt statt geschnitten.
KURZ = rough_cut.MIN_CLIP * 2


def main(path: Path) -> int:
    if not path.exists():
        print(f"Datei nicht gefunden: {path}")
        return 2

    info = media.probe(path)
    if not info.has_audio:
        print(f"{path.name} hat keine Tonspur — der Rohschnitt hat nichts zu hören.")
        return 2

    print(f"{path.name}: {info.duration:.1f}s, {info.audio_codec or 'Ton'}\n")

    loud = rough_cut.detect_silence(path)
    if not loud:
        print("auto-editor hat nichts gefunden.")
        print("  Entweder ist es nicht installiert (pip install auto-editor),")
        print("  oder in dieser Aufnahme ist nirgends Stille. Beides muss vor")
        print("  der richtigen Aufnahme geklärt sein.")
        return 1

    keep = rough_cut.apply_safety(loud)
    gesprochen = sum(e - s for s, e in keep)
    still_pct = (info.duration - gesprochen) / info.duration * 100
    kurze = [e - s for s, e in keep if e - s < KURZ]

    print(f"  Stille erkannt      {still_pct:5.1f} %")
    print(f"  Segmente            {len(keep)}")
    print(f"  davon unter {KURZ:.1f}s   {len(kurze)}")

    laengste = max((e - s for s, e in _luecken(keep, info.duration)), default=0.0)
    print(f"  längste Pause       {laengste:5.2f}s\n")

    ok = True
    if still_pct < ZU_WENIG:
        ok = False
        print(f"ZU LAUT. Nur {still_pct:.1f} % der Aufnahme gelten als Pause. Der")
        print("Rohschnitt wird fast nichts entfernen. Fenster zu, Lüfter aus,")
        print("Mikro näher ran — und dann noch einmal messen.")
    elif still_pct > VIEL:
        print(f"Sehr viel Pause ({still_pct:.1f} %). Nicht falsch, wenn du bewusst")
        print("langsam sprichst — sonst ist das Mikro vermutlich zu weit weg und")
        print("schluckt leise Wortanfänge.")

    if laengste and laengste < rough_cut.MIN_GAP * 3:
        ok = False
        print(f"Die längste Pause ist {laengste:.2f}s. Ab {rough_cut.MIN_GAP}s wird")
        print("überhaupt geschnitten, ab 0,5s entsteht eine saubere Phrasengrenze.")
        print("Zwischen den Sätzen bewusst eine ganze Sekunde stehen lassen.")

    if len(kurze) > len(keep) / 3:
        print(f"{len(kurze)} von {len(keep)} Segmenten sind kürzer als {KURZ:.1f}s.")
        print("Das sieht nach abgehacktem Sprechen oder nach Rauschen aus, das")
        print("stellenweise als Sprache durchgeht.")

    if ok and still_pct >= ZU_WENIG:
        print("Der Raum taugt. Der Rohschnitt findet die Pausen.")
    return 0 if ok else 1


def _luecken(keep: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    gaps, prev = [], 0.0
    for start, end in keep:
        if start > prev:
            gaps.append((prev, start))
        prev = end
    if duration > prev:
        gaps.append((prev, duration))
    return gaps


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1])))
