# POGO GNOM — Aufnahmeplan

Abgeleitet aus den tatsächlichen Schwellwerten im Schnitt-Tool
(`ai-video-editor/engine/rough_cut.py`), nicht aus allgemeinen Ratschlägen.
Stand: 24. August 2026. Bezieht sich auf `YOUTUBE-SKRIPT.md` (11:00).

---

## Warum diese Regeln

Der automatische Rohschnitt entfernt Stille, Füllwörter, Wiederholungen und
abgebrochene Anfänge. Er kann das nur, wenn die Aufnahme ihm die Signale gibt,
auf die er hört. Vier Zahlen bestimmen alles:

| Schwelle | Wert | Bedeutung für dich |
|---|---|---|
| `MIN_GAP` | **150 ms** | Kürzere Pausen werden **nicht** geschnitten — sie liegen mitten im Wort |
| `MIN_CLIP` | **400 ms** | Kürzere Schnipsel gelten als Atmer und fliegen raus |
| Phrasengrenze | **500 ms** | Ab hier bricht das Transkript eine neue Phrase an |
| Wiederholungsfenster | **4 s** | Dieselbe Phrase zweimal innerhalb 4 s = Retake, der **erste** fliegt raus |

---

## Die fünf Regeln

**1. Verhaspler: Satz komplett neu anfangen.**
Nicht mitten im Satz reparieren. Sagst du „Der Gnom springt — äh — der Gnom
springt über Pilze", erkennt das Tool die Wiederholung und behält den zweiten
Anlauf. Reparierst du mittendrin, bleibt der Murks stehen, weil keine
vollständige Phrase doppelt vorkommt.

**2. Zwischen Takes eine ganze Sekunde stehen lassen.**
Nicht „Satz zu Ende, sofort weiter". Eine Pause unter 150 ms ist als Schnitt
unsicher, ab 500 ms wird sie zur sauberen Phrasengrenze. Eine Sekunde ist
großzügig und kostet dich nichts — sie fliegt ohnehin raus.

**3. Zahlen immer mit ihrer Einheit im selben Satz.**
„Achtzehn Monate", „387 Commits", „vierzig Prozent". Das ist genau das Signal,
das eine Grafik auslöst. „Ich hab lange dran gesessen" löst nichts aus und ist
als Aussage auch schwächer.

**4. Zwei Zahlen in einem Satz nur, wenn sie dasselbe messen.**
„31 401 geschrieben, 5 338 gelöscht" wird zum Balkendiagramm — gleiche Einheit.
„800 Meter, zehn Zonen" wird bewusst **kein** Diagramm, weil Meter und Zonen
nichts gemeinsam haben.

**5. Guter Ton ist keine Kür.**
Der ganze Rohschnitt hängt an der Stille-Erkennung. Ein rauschiger Raum heißt:
keine Stille, kein automatischer Schnitt. Mikro nah, Fenster zu, Lüfter aus.

---

## Reihenfolge der Sprachaufnahme

Nicht chronologisch. In dieser Reihenfolge, weil die schwersten Passagen die
frischeste Stimme brauchen:

| # | Skript-Abschnitt | Warum hier |
|---|---|---|
| 1 | **7:30 Das Geständnis** | Der ehrlichste Moment. Braucht Ruhe und darf nicht montiert klingen — im Skript steht ausdrücklich „kein Schnitt". |
| 2 | **9:00–10:20 Steam-Kapitel** | Fünf Fehler hintereinander, viel Text |
| 3 | **2:45–5:00 Die sieben Fehler** | Das Herzstück, längste Strecke |
| 4 | **0:08–0:45 Prämisse + KI-Frage** | Muss sitzen, ist aber kurz |
| 5 | **0:50–2:30 Was das Spiel ist** | Erklärend, verzeiht mehr |
| 6 | **5:15–7:30 Was gut geworden ist** | Ebenso |
| 7 | **10:20–11:00 Abschluss** | Kurz, am Ende |
| 8 | **0:00–0:08 Hook** | Zuletzt, wenn du den Ton des Videos im Ohr hast |

Pro Abschnitt in einem Rutsch sprechen, nicht Satz für Satz. Die
Wiederholungserkennung braucht zusammenhängende Takes.

---

## Gameplay-Aufnahmen

Faustregel: **das Dreifache der Endlänge.** Für elf Minuten also gut 30 Minuten
sauberes Capture.

### Dateinamen

Die B-Roll-Zuordnung sucht aktuell im **Dateinamen**. Also nicht
`capture_0034.mp4`, sondern:

```
broll_zone1_rasen_01.mp4
broll_zone7_ballons_02.mp4
broll_sturz_lang_01.mp4
broll_bescheid_stempel_01.mp4
broll_garderobe_01.mp4
```

### Pflichtaufnahmen aus dem Skript

| Skript | Was genau |
|---|---|
| 0:00 Hook | Gnom taumelt vom Himmel, schlägt auf. Danach Bescheid mit Stempel. |
| 0:50 | Aufstieg durch mehrere Zonen, schnell |
| 1:20 | Drei Bescheide nacheinander |
| 2:45–5:00 | **Vorher/Nachher zu jedem der sieben Fehler** — schwebende Berge, verschwindender Fluss, zu helle Texturen, Geisterbrett, Pilzhut |
| 5:15 | Figuren-Durchlauf, Truhe, Garderobe |
| 7:30 | Übungsgelände, Zone Mond wählen, erster Sprung |
| 9:00 | Terminal mit „Successfully finished build" |
| 9:00 | Steamworks-Achievement-Liste mit den falschen Namen |
| 9:00 | **Zehn Erfolgs-Einblendungen hintereinander** |
| 9:00 | **Startgarten voll vs. leer** |

Die letzten beiden sind die wertvollsten Aufnahmen des Videos. Beide lassen
sich wiederherstellen: Erfolge in Steamworks zurücksetzen und neu starten; der
leere Garten über das alte Speicherprofil.

---

## Die Grafiken

Elf sind bereits gerendert (1920×1080, Alphakanal, Design `light_card`).
Verankert werden sie an gesprochenen Wörtern, nicht an Zeitpunkten — schneidest
du um, wandern sie mit.

| Datei | Skript | Anker |
|---|---|---|
| `0-45_kapitel` | 0:45 | Kapitelkarte |
| `0-08_zahlenkarte1` | 0:08 | „26 063" |
| `0-08_geschrieben_geloescht` | 0:08 | „31 401" |
| `2-30_landefenster` | 2:30 | Vollbild, kein Anker |
| `5-15_zahlenkarte2` | 5:15 | „acht" |
| `5-15_drawcalls` | 5:15 | „991" |
| `5-15_verschmolzen` | 5:15 | „3 728" |
| `9-00_kapitel` | 9:00 | Kapitelkarte |
| `9-00_neun_fehler` | 9:00 | „neun" |
| `9-00_geometrie` | 9:00 | „44" |
| `10-20_bilanz` | 10:20 | „387" |

Noch offen, weil Bildmaterial nötig: die Pogo-Physik-Animation (1:45, zwei
Balken an einem gemeinsamen Regler) und die Vorher/Nachher-Gegenüberstellungen.

---

## Vor der Aufnahme klären

Drei Widersprüche zwischen den Projektdokumenten. Zahlen im Video werden
nachgerechnet.

1. **Draw Calls:** Skript sagt `991 → 884 → 730`, `UEBERGABE-YOUTUBE.md` sagt
   `968 → 730`. Die gerenderte Grafik nutzt die Skript-Fassung.
2. **Kosmetikteile:** Zahlenkarte 2 sagt **54**, die Steam-Beschreibung im
   selben Dokument sagt **62**.
3. **Neun Fehler in zwei …?** `UEBERGABE-YOUTUBE.md` sagt „Stunden",
   `ECKDATEN.md` und das Skript sagen „Tage". ECKDATEN ist neuer.

Dazu eine Zählung, die stolpert: Die Kapitelkarte bei 0:45 sagt „7 Fehler",
danach zählt das Skript bis Fehler 12 und spricht von neun Steam-Fehlern.
Wer mitzählt, kommt nicht auf.

---

## Ablauf am Schnitttag

```bash
# 1. Alles in einen Ordner, dann
./start.sh                       # → http://127.0.0.1:8000

# 2. Sprachaufnahme hineinziehen. Es läuft automatisch:
#    Analyse → Transkript → Rohschnitt → Vorschläge

# 3. Vorschläge durchgehen (Sammelaktionen oben in der Liste)

# 4. Gerenderte Grafiken in den Projektordner unter graphics/
#    und im EDL an ihr Wort hängen

# 5. Vorschau, dann Export
```

Erwartungswert für elf Minuten Rohmaterial auf einem Laptop ohne
Grafikkarte: **Analyse gut zwei Minuten**, Vorschau-Render etwa
**zweieinhalb Minuten**, finaler 1080p-Export etwa **fünf Minuten**.
Die Transkription kommt dazu und ist der einzige Schritt, der wirklich von
einer Grafikkarte profitiert.
