#!/usr/bin/env python3
"""Vorher/Nachher-Gegenüberstellungen für den POGO GNOM Devlog.

Die Fehler sind der Kern des Videos, und ein Satz wie „die Berge schwebten"
ist ohne Bild eine Behauptung. Sechs davon sind Zustände und keine Vorgänge —
je zwei Screenshots reichen, Videomaterial braucht es nicht.

    python beispiele/pogo-gnom/vergleiche.py [ziel-ordner]

Das Skript baut, was da ist, und sagt, was fehlt. Es erfindet nichts: für
jeden Fehler ohne Screenshots steht am Ende, welche zwei Dateien gebraucht
werden. Ablegen unter `ASSETS/broll/` mit genau diesen Namen.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.compare import CompareSpec, build_comparison  # noqa: E402
from engine.graphics import make_style                    # noqa: E402

THEME = "light_card"
ASSETS = Path(__file__).resolve().parents[2] / "ASSETS" / "broll"

# (Kürzel, Ankerwort, Beschriftung links, Beschriftung rechts)
#
# Das Ankerwort ist das gesprochene Wort, auf dem die Gegenüberstellung liegen
# soll — nicht ein Zeitpunkt. Schneidest du um, wandert sie mit.
#
# Die Ankerwörter stehen so im Skript (`YOUTUBE-SKRIPT.md`), sind also echter
# gesprochener Text und nicht abgeleitet. Trotzdem nach der Aufnahme gegen das
# Transkript prüfen: sagst du den Satz anders, findet die Ankerauflösung das
# Wort nicht und meldet es.
FEHLER = [
    # Fehler 2-5 und 7 aus dem Kapitel „Die Fehler" (2:45-5:00)
    ("berge", "schwebten", "schwebend", "verankert"),
    ("fluss", "verschwand", "Fluss weg", "Fluss da"),
    ("texturen", "aufgehellt", "Stein weiß", "Stein grau"),
    ("brett", "Holzbrett", "Geisterbrett", "entfernt"),
    ("pilzhut", "Pilzhut", "halbiert", "frei"),
    # Fehler 12 aus dem Steam-Kapitel (9:00). Das Skript nennt es die Pointe,
    # und der Aufnahmeplan zählt es zu den zwei wertvollsten Aufnahmen.
    # Richtung wie überall: links der Fehler, rechts die Behebung.
    ("startgarten", "fehlt", "leer geräumt", "wieder da"),
]

# Fehler 1 (das tote englische Gartenamt) und Fehler 6 (69 kaputte Kameras)
# sind die beiden restlichen aus dem Siebener-Kapitel. Beide bekommen KEINE
# Gegenüberstellung: der eine ist eine Codezeile, der andere eine Zählung —
# für beide sieht ein Vorher/Nachher-Bild gleich aus.


def paths_for(key: str) -> tuple[Path, Path]:
    return ASSETS / f"{key}_vorher.png", ASSETS / f"{key}_nachher.png"


def build(out_dir: Path) -> tuple[list[Path], list[str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    st = make_style(THEME, width=1920, height=1080, fps=30,
                    reserve_caption_band=False)
    # Etwas länger als der Standard: der Zuschauer soll den Fehler erst finden,
    # bevor er verschwindet.
    spec = CompareSpec(hold_before=1.0, sweep=1.8, hold_after=1.6)

    gebaut: list[Path] = []
    fehlt: list[str] = []

    for key, anchor, links, rechts in FEHLER:
        vorher, nachher = paths_for(key)
        missing = [p.name for p in (vorher, nachher) if not p.exists()]
        if missing:
            fehlt.append(f"{key:10} → {', '.join(missing)}   (Anker: „{anchor}“)")
            continue
        out = build_comparison(vorher, nachher, out_dir / f"vergleich_{key}.mov",
                               links, rechts, st, spec)
        gebaut.append(out)
        print(f"  {out.name:28} {out.stat().st_size / 1024:7.0f} KB   "
              f"Anker: „{anchor}“")

    return gebaut, fehlt


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("vergleiche")
    print(f"POGO GNOM — Gegenüberstellungen nach {target}/\n")
    gebaut, fehlt = build(target)

    if gebaut:
        print(f"\n{len(gebaut)} gebaut, Design '{THEME}', 1920x1080.")
    if fehlt:
        print(f"\nNoch nicht gebaut, weil die Dateien fehlen "
              f"(nach {ASSETS} legen):")
        for line in fehlt:
            print(f"  {line}")
    if not gebaut and not fehlt:
        print("Nichts zu tun.")
