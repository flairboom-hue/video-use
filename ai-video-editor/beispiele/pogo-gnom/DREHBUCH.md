# POGO GNOM — Drehbuch und Aufnahmeanleitung

Was hier **nicht** steht: die Sätze. Die stehen in `YOUTUBE-SKRIPT.md` und
sollen ausdrücklich nicht neu erfunden werden. Hier steht, **wann** du welchen
Block sprichst, **wie** du ihn sprichst und **womit** du ihn aufnimmst.

Die Blocknamen und Zeitmarken unten stammen aus `AUFNAHMEPLAN.md` — dort steht
auch, was der automatische Schnitt braucht (die fünf Regeln) und welche Grafiken
und Gegenüberstellungen wo landen. Dieses Dokument doppelt das nicht, es baut
darauf auf.

---

## Zuerst: sechzig Sekunden, bevor du vierzig Minuten aufnimmst

Der ganze automatische Rohschnitt hängt an einer einzigen Annahme — dass Pausen
leiser sind als Sprache. In einem Raum mit Lüfter, Straße oder Rechnerrauschen
stimmt das nicht mehr, und dann entfernt der Rohschnitt nichts. Das merkst du
sonst erst, wenn alles im Kasten ist.

Also: eine Minute sprechen wie im Video, mit echten Pausen zwischen den Sätzen,
und messen.

```
python scripts/tontest.py probe.mp4
```

```
  Stille erkannt       40.0 %
  Segmente            10
  längste Pause        2.40s

Der Raum taugt. Der Rohschnitt findet die Pausen.
```

Kommt stattdessen **ZU LAUT** heraus, ist der Raum das Problem und nicht die
Einstellung: Fenster zu, Lüfter aus, Mikro näher ran, noch einmal messen. Erst
wenn das steht, lohnt sich der Rest.

Danach dieselbe Minute einmal komplett durch das Werkzeug schicken — hochladen,
analysieren, Rohschnitt anschauen. Ein Problem nach einer Minute ist ein
Ärgernis, dasselbe Problem nach vierzig Minuten ist ein Drehtag.

---

## Der Aufbau

### Ton

**Eine Quelle.** Nicht Kamera plus separater Recorder. Die ganze Kette hängt an
*einer* Datei: Transkript, Wortzeiten, Anker, Untertitel. Zwei Quellen heißen
synchronisieren, und jeder Versatz verschiebt am Ende die Untertitel.

**Mikro nah**, 20–30 cm, leicht seitlich versetzt statt frontal — dann treffen
Plosive nicht direkt auf die Kapsel.

**Kein Noise Gate beim Aufnehmen.** Es klingt sauberer und macht das Transkript
schlechter: Gates schneiden leise Wortanfänge und Zischlaute ab, und genau die
braucht die Spracherkennung für saubere Wortgrenzen. Ungenaue Wortgrenzen heißen
verrutschte Anker und verrutschte Untertitel. Lieber ein leiser Raum als ein
Gate.

**Zehn Sekunden Raumton** am Anfang jeder Session aufnehmen, bevor du sprichst.
Kostet nichts und rettet dich, falls doch entrauscht werden muss.

**Kopfhörer auf.** Ein Problem, das du beim Aufnehmen hörst, kostet einen Take.
Dasselbe Problem beim Schnitt kostet den Drehtag.

### Kamera

**Objektiv auf Augenhöhe**, und in die Linse schauen, nicht auf das
Vorschaubild. Der Unterschied ist klein auf dem Monitor und groß im Video: Blick
auf den eigenen Sucher liest sich als Blick an den Zuschauer vorbei.

**Bildrate wie beim Veröffentlichen.** Das Werkzeug übernimmt die Bildrate der
Quelle, es rechnet nichts um.

**Zwei Bildtypen, und sie hängen an den Grafiken.** Die Grafikkarten sind
Vollbreite-Platten — sie reichen von 6 % bis 94 % der Bildbreite und liegen
mittig. Über deinem Gesicht liegt dann eine Karte. Also:

| | Bild | Blöcke |
|---|---|---|
| **A** | Talking Head | Blöcke **ohne** Grafik: Hook, das Geständnis, Abschluss |
| **B** | Ton über Spielaufnahme | Blöcke **mit** Grafik oder Gegenüberstellung |

Praktisch: sprich alles als Talking Head, aber sorge dafür, dass für jeden Block
aus Spalte B genug Spielmaterial da ist, auf das geschnitten werden kann. Ohne
das hast du eine Grafik, die über deinem Kopf klebt.

**Untere 26 % des Bildes freihalten.** Da liegen die Untertitel. Kinn oberhalb
dieser Linie, und nichts Wichtiges darunter.

### Licht

Ein Hauptlicht, eine Aufhellung, gleiche Farbtemperatur. Mehr braucht es nicht,
und gemischtes Licht ist der einzige Fehler, den man später kaum wegbekommt.

Das Grafikdesign `light_card` ist bewusst so gewählt, dass es sowohl über den
hellen Rasenzonen als auch über den dunklen Mondzonen lesbar bleibt — es bringt
seine eigene Platte mit. Dein Licht muss dazu nichts leisten.

---

## Wie du sprichst

**Zu einer Person, nicht zu einem Publikum.** „Ich zeig dir mal" statt „In
diesem Video werden wir uns anschauen". Das ist der Ton, den das Skript
ohnehin hat.

**Etwa zehn Prozent über deiner normalen Energie.** Der Schnitt entfernt jeden
Anlauf, jedes Absetzen, jedes Nachdenken. Was übrig bleibt, ist dichter als das,
was du gesprochen hast, und muss diese Dichte tragen.

**Tempo normal.** Nicht schneller sprechen, weil geschnitten wird — das
Werkzeug entfernt die Pausen, du nicht. Hetzen macht nur die Wortgrenzen
unsauber.

**Nicht ablesen.** Den Gedanken kennen, dann sagen. Ein abgelesener Satz ist im
Video hörbar, und die Wiederholungserkennung erlaubt dir ohnehin, denselben Satz
dreimal anzugehen und nur den letzten zu behalten.

**Ankerwörter deutlich und möglichst einmal.** Eine Grafik hängt an einem
gesprochenen Wort. Sagst du „Berge" dreimal im Block, landet sie beim ersten
Vorkommen — korrigierbar, aber unnötige Arbeit.

Die fünf Regeln zum Verhaspeln, zu Pausen zwischen Takes und zu Zahlen mit
Einheit stehen in `AUFNAHMEPLAN.md`. Die gelten hier alle.

### Das Geständnis bei 7:30 ist die Ausnahme

Für diese Stelle ist im Skript **kein Schnitt** vorgesehen. Das heißt: dieser
Take muss in einem Stück tragen — kein Retake mitten drin, keine Reparatur
hinterher.

Also eigene Session, ausgeruht, vier bis sechs vollständige Anläufe, jeder von
vorne bis hinten. Danach entscheidest du beim Sichten, welcher der ganze ist.
Nicht der technisch sauberste gewinnt.

---

## Ablauf pro Take

1. **Ansage:** „Block 7:30, Take 2." Sie bleibt im Transkript stehen und wird
   beim Sichten von Hand entfernt — dafür findest du jeden Take wieder.
2. **Eine ganze Sekunde still.** Nicht sofort losreden.
3. **Block in einem Rutsch sprechen.** Nicht Satz für Satz — die
   Wiederholungserkennung braucht zusammenhängende Takes.
4. **Wieder eine Sekunde still**, bevor du dich bewegst oder etwas sagst.

---

## Der Drehplan

| Zeit | Block | Bild | Was dazu liegt | Ton |
|---|---|---|---|---|
| 0:00 | Hook | **A** + Sturz, Bescheid mit Stempel | — | Kein Anlauf. Erster Satz ist der erste Satz. |
| 0:08 | Prämisse + KI-Frage | **B** | Zahlenkarte, Balken geschrieben/gelöscht | Nüchtern. Die Zahlen tragen sich selbst. **Achtung:** der Satz „keine generierte Musik" darf so nicht fallen — siehe `AUFNAHMEPLAN.md`. |
| 0:45 | Kapitel „7 Fehler" | **B** | Kapitelkarte | Kurz, als Übergang. |
| 0:50 | Was das Spiel ist | **B** — Aufstieg durch Zonen | — | Erklärend, verzeiht am meisten. |
| 1:20 | Drei Bescheide | **B** | — | Rhythmisch, die drei kommen nacheinander. |
| 1:45 | Pogo-Physik | **B** — Sprungaufnahme | Regler „Ladung", zwei Balken | Ruhig. Die Grafik erklärt, du benennst nur. |
| 2:30 | Landefenster | **B** — Vollbild | Waagerechtes Balkendiagramm, elf Zonen | Lass der Grafik Zeit, elf Zeilen liest niemand nebenbei. |
| 2:45–5:00 | **Die sieben Fehler** | **B** | Fünf Vorher/Nachher-Wischblenden, zwei Grafiken | Herzstück. Pro Fehler: was war, was ich dachte, was es war. |
| 5:15 | Was gut geworden ist | **B** — Figuren, Truhe, Garderobe | Zahlenkarte 2, Draw Calls, verschmolzen | Hörbar anderer Ton als davor — hier darf Freude rein. |
| 7:30 | **Das Geständnis** | **A** | — | Kein Schnitt. Siehe oben. |
| 9:00 | Steam-Kapitel | **B** — Terminal, Achievements, Startgarten | Kapitelkarte, neun Fehler, 44 %, Wischblende Startgarten | Trocken. Die Fehler sind komisch genug ohne Hilfe. |
| 10:20 | Bilanz | **B** | Zahlenkarte 3 | Zurückblickend, nicht triumphierend. |
| 10:20–11:00 | Abschluss | **A** | — | Kurz. Nicht um einen Appell herum bauen. |

Die beiden wertvollsten Spielaufnahmen stehen bei 9:00: **zehn
Erfolgs-Einblendungen hintereinander** und **Startgarten voll gegen leer**.
Beide sind wiederherstellbar (Erfolge in Steamworks zurücksetzen, alter
Spielstand für den leeren Garten) — aber beide brauchen Vorbereitung, nicht
Glück. Plane sie als eigenen Termin.

---

## Der Aufnahmetag

1. Raumton, zehn Sekunden.
2. `scripts/tontest.py` an einer Minute. Erst weiter, wenn er grün ist.
3. Diese Minute einmal komplett durch das Werkzeug.
4. **7:30 Das Geständnis** — frischeste Stimme, schwerster Block.
5. **9:00–10:20 Steam-Kapitel**.
6. Pause. Wirklich.
7. **2:45–5:00 Die sieben Fehler** — längste Strecke.
8. **0:08–0:45**, dann **0:50–2:30**, dann **5:15–7:30**, dann **10:20–11:00**.
9. **0:00 Hook** zuletzt, wenn du den Ton des ganzen Videos im Ohr hast.

Die Reihenfolge steht so auch in `AUFNAHMEPLAN.md` und ist keine Bequemlichkeit:
die schwersten Passagen bekommen die frischeste Stimme, und der Hook profitiert
davon, dass du schon weißt, wie das Video klingt.

---

## Checkliste vor dem ersten Take

- [ ] Fenster zu, Lüfter aus, Handy stumm
- [ ] `scripts/tontest.py` sagt „Der Raum taugt"
- [ ] Testminute einmal durch das Werkzeug gelaufen
- [ ] Raumton aufgenommen
- [ ] Objektiv auf Augenhöhe, Blick in die Linse
- [ ] Untere 26 % des Bildes frei
- [ ] Kopfhörer auf, Pegel geprüft
- [ ] Speicherkarte leer, Akku voll, Netzteil dran
- [ ] Wasser in Reichweite, nicht im Bild
