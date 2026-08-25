#!/usr/bin/env python3
"""Rebuild every graphic for the POGO GNOM devlog.

Kept as a script rather than a folder of .mov files: the numbers are still
being reconciled across the project's documents, and a script is a diff away
from correct where a rendered clip is a re-export away.

    python beispiele/pogo-gnom/grafiken.py [ziel-ordner]

Figures are sourced from YOUTUBE-SKRIPT.md (24 August 2026). Where the project
documents disagree, the script's own version is used and the conflict is noted
in AUFNAHMEPLAN.md — the video says what the script says.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.graphics import (  # noqa: E402
    bar_chart, bar_chart_h, comparison, linked_meters, make_style,
    number_animation, stat_card, text_animation,
)

# light_card carries its own plate, so the graphics stay readable over both the
# bright lawn zones and the dark moon zones without a second version.
THEME = "light_card"


def build(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    st = make_style(THEME, width=1920, height=1080, fps=30,
                    reserve_caption_band=False)
    made: list[Path] = []

    def keep(path: Path) -> Path:
        made.append(path)
        print(f"  {path.name:34} {path.stat().st_size / 1024:7.0f} KB")
        return path

    # 0:45 · Kapitelkarte
    keep(text_animation(out_dir / "0-45_kapitel.mov", "7 Fehler", st))

    # 0:08 · Zahlenkarte 1
    keep(stat_card(out_dir / "0-08_zahlenkarte1.mov", [
        ("26 063", "Zeilen"), ("1", "Datei"), ("36", "Tage"), ("387", "Commits"),
    ], st))

    # 0:08 · geschrieben gegen gelöscht — gleiche Einheit, also ein Diagramm
    keep(bar_chart(out_dir / "0-08_geschrieben_geloescht.mov",
                   [31401, 5338], ["geschrieben", "gelöscht"], st,
                   suffix=" Zeilen"))

    # 1:45 · Pogo-Physik. Ein Regler, zwei Balken: die Ladung bestimmt Höhe
    # UND Weite, man kann also nicht das eine ohne das andere haben. Genau das
    # sagen zwei statische Balken nicht — der gemeinsame Regler schon.
    #   Sprung senkrecht   vy = 9 + Ladung * 15
    #   Sprung waagerecht  h  = 3 + Ladung * 8
    keep(linked_meters(out_dir / "1-45_pogophysik.mov", "Ladung", [
        ("Höhe", 9.0, 15.0, ""), ("Weite", 3.0, 8.0, ""),
    ], st))

    # 2:30 · Landefenster. Elf benannte Zonen: waagerecht, weil senkrechte
    # Balken bei elf Kategorien die Beschriftung kippen müssten.
    keep(bar_chart_h(out_dir / "2-30_landefenster.mov", [
        ("Rasen", 52), ("Blumenbeet", 40), ("Wolken", 31), ("Gartenweg", 29),
        ("Ast", 23), ("Dach", 22), ("Antenne", 13), ("Schnur", 12.4),
        ("Ballons", 10.9), ("Mond", 8.8), ("Ziel", 7.0),
    ], st, suffix=" %"))

    # 5:15 · Zahlenkarte 2
    keep(stat_card(out_dir / "5-15_zahlenkarte2.mov", [
        ("8", "Figuren"), ("54", "Kosmetikteile"),
        ("7", "Sprachen"), ("251", "Kollisionsflächen"),
    ], st))

    # 5:15 · Draw Calls
    keep(bar_chart(out_dir / "5-15_drawcalls.mov",
                   [991, 884, 730], ["Anfang", "Mitte", "Jetzt"], st))

    # 5:15 · zusammengeschmolzen
    keep(comparison(out_dir / "5-15_verschmolzen.mov", 3728, 93,
                    "EINZELOBJEKTE", "ZUSAMMENGESCHMOLZEN", "", st))

    # 9:00 · Steam-Kapitel
    keep(text_animation(out_dir / "9-00_kapitel.mov",
                        "Fertig heißt nicht fertig", st))
    keep(number_animation(out_dir / "9-00_neun_fehler.mov", 9,
                          "Fehler in zwei Tagen", "", st))
    keep(number_animation(out_dir / "9-00_geometrie.mov", 44,
                          "weniger Geometrie", "%", st))

    # 10:20 · Bilanz
    keep(stat_card(out_dir / "10-20_bilanz.mov", [
        ("36", "Tage"), ("387", "Commits"),
        ("26 063", "Zeilen"), ("9", "Fehler zuletzt"),
    ], st))

    return made


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("grafiken")
    print(f"POGO GNOM — Grafiken nach {target}/\n")
    built = build(target)
    print(f"\n{len(built)} Grafiken, Design '{THEME}', 1920x1080 mit Alphakanal.")
