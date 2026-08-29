# POGO GNOM — die Screenshots für die Gegenüberstellungen

Acht Vorher/Nachher-Paare: die sieben Fehler aus dem Kapitel 2:45–5:00 und der
leergeräumte Startgarten aus dem Steam-Kapitel. **Sechzehn Bilder**, keine
Videos — alle acht sind Zustände, keine Vorgänge.

Ablegen unter `ASSETS/broll/` mit genau diesen Namen, dann:

```
python beispiele/pogo-gnom/vergleiche.py vergleiche
```

Das Skript baut, was da ist, und listet auf, was noch fehlt. Du kannst also
Stück für Stück liefern.

---

## Die drei Regeln, ohne die es nicht funktioniert

**1. Gleicher Kamerastandort.** Das ist die wichtige. Die Wischblende legt
beide Zustände an dieselbe Stelle im Bild; wandert die Kamera zwischen den
Aufnahmen, liest sich das als Kamerafahrt statt als Veränderung — und der
Fehler, den du zeigen willst, geht darin unter. Wenn möglich: Position
speichern, Zustand umschalten, ohne die Kamera anzufassen erneut auslesen.

**2. Gleiche Auflösung, gleiche Tageszeit, gleiches Wetter.** Alles, was sich
sonst noch mitverändert, kostet Aufmerksamkeit.

**3. PNG, nicht JPG.** JPG-Artefakte an harten Kanten fallen in einer
Gegenüberstellung auf, weil das Auge genau dort hinschaut.

---

## Die acht Paare

### 1 · Das tote englische Gartenamt

| | |
|---|---|
| Dateien | `gartenamt_vorher.png` · `gartenamt_nachher.png` |
| Anker | „englische" |
| **vorher** | Spiel auf **Englisch** gestellt, ein Bescheid auf dem Bildschirm — Text auf **Deutsch** |
| **nachher** | Derselbe Bescheid, dieselbe Stelle, Text auf **Englisch** |

Das Symptom ist sichtbarer als die Ursache: die Codezeile `lang === 'en'`
zeigst du als Grafik daneben, aber was der Zuschauer *versteht*, ist ein
englischer Spieler mit deutscher Post.

Braucht den alten Zustand — alter Build, alter Screenshot, oder den Vergleich
für eine Minute zurückdrehen.

---

### 2 · Die schwebenden Berge

| | |
|---|---|
| Dateien | `berge_vorher.png` · `berge_nachher.png` |
| Anker | „schwebten" |
| **vorher** | Blick zum Horizont, Berge schweben über der Kante, der Boden darunter verblasst im Nebel |
| **nachher** | Gleicher Blick, Berge sitzen auf dem Boden |

Laut Skript hängt das an **einer einzigen Einstellung** — die lässt sich
vermutlich kurz zurückdrehen, ohne einen alten Build zu brauchen.

---

### 3 · Der verschwindende Fluss

| | |
|---|---|
| Dateien | `fluss_vorher.png` · `fluss_nachher.png` |
| Anker | „verschwand" |
| **vorher** | **Flacher Blickwinkel aus der Ferne** — Fluss weg, die Ufer schieben sich vor das Wasser |
| **nachher** | Gleicher flacher Blickwinkel, Fluss sichtbar |

Wichtig: **nicht von oben.** Von oben sah es immer richtig aus — das ist im
Skript sogar der Grund, warum tagelang an der falschen Stelle gesucht wurde.
Ein Vorher-Bild von oben zeigt den Fehler nicht.

---

### 4 · Alles war zu hell

| | |
|---|---|
| Dateien | `texturen_vorher.png` · `texturen_nachher.png` |
| Anker | „aufgehellt" |
| **vorher** | Stein wirkt **weiß**, Holz blass |
| **nachher** | Gleiche Stelle, Stein grau, Holz mit Farbe |

Such dir eine Stelle, an der **Stein und Holz zusammen** im Bild sind — das
Skript nennt beide, und zwei Materialien nebeneinander machen den Unterschied
deutlicher als eine große graue Fläche.

Laut Skript **eine fehlende Zeile**, also vermutlich kurz zurückdrehbar.

---

### 5 · Das Geisterbrett

| | |
|---|---|
| Dateien | `brett_vorher.png` · `brett_nachher.png` |
| Anker | „Holzbrett" |
| **vorher** | Startbereich, ein braunes Holzbrett liegt auf dem Rasen |
| **nachher** | Gleicher Blick, Brett weg |

Nah genug ran, dass das Brett groß im Bild liegt. Bei einer Weitwinkel-Übersicht
verschwindet es zwischen dem Gras, und dann sieht der Zuschauer nur zweimal
denselben Rasen.

---

### 6 · Die 69 kaputten Kameras

| | |
|---|---|
| Dateien | `kameras_vorher.png` · `kameras_nachher.png` |
| Anker | „geschätzt" |
| **vorher** | Trailerbild mit einem echten Regelverstoß: Kamera steckt **in** einer Plattform, oder die Figur ist **außerhalb** des Bildes |
| **nachher** | Dieselbe Trailer-Einstellung, sauber im Bild |

Nimm das deutlichste der 69 — eine Kamera in einer Plattform ist sofort
lesbar, eine Figur knapp am Rand nicht.

Der Trailer wird laut Skript **aus dem Spiel gerendert, immer identisch**.
Wenn du den alten Stand noch hast, ist das Vorher-Bild ein Rendern entfernt.

---

### 7 · Der Pilzhut *(die Pointe)*

| | |
|---|---|
| Dateien | `pilzhut_vorher.png` · `pilzhut_nachher.png` |
| Anker | „Pilzhut" |
| **vorher** | Der Gnom, vom Pilzhut mittendurch geschnitten — **Kopf frei, Körper verdeckt** |
| **nachher** | Gleiche Einstellung, Gnom ganz zu sehen |

Das ist die einzige, bei der du wahrscheinlich **keinen alten Stand brauchst**:
Der Pilz existiert ja noch. Es ist eine Kameraposition, und die lässt sich
nachstellen.

Der Kopf muss frei sein und der Körper verdeckt — genau das ist die Pointe.
Ein Bild, in dem auch der Kopf verdeckt ist, erzählt die Geschichte nicht.

---

### 8 · Der leergeräumte Startgarten *(9:00, die Pointe des Steam-Kapitels)*

| | |
|---|---|
| Dateien | `startgarten_vorher.png` · `startgarten_nachher.png` |
| Anker | „fehlt" |
| **vorher** | Startgarten **leer**: Gartenwerkzeug weg, Kisten weg, Bäume kahl |
| **nachher** | Startgarten vollständig |

Links steht der **leere** Garten — Fehler zuerst, Behebung danach, wie bei
allen anderen. Das Skript nennt die Reihenfolge andersherum („voll · leer"),
meint damit aber die Erzählung, nicht die Blende.

Laut Aufnahmeplan über das alte Speicherprofil wiederherstellbar.

---

## Zusammengefasst als Einkaufsliste

```
ASSETS/broll/
  gartenamt_vorher.png     gartenamt_nachher.png
  berge_vorher.png         berge_nachher.png
  fluss_vorher.png         fluss_nachher.png
  texturen_vorher.png      texturen_nachher.png
  brett_vorher.png         brett_nachher.png
  kameras_vorher.png       kameras_nachher.png
  pilzhut_vorher.png       pilzhut_nachher.png
  startgarten_vorher.png   startgarten_nachher.png
```

Am leichtesten dürften **Pilzhut** (nur eine Kameraposition), **Berge** und
**Texturen** (je eine Einstellung bzw. Zeile) und **Startgarten** (altes
Speicherprofil) sein. **Gartenamt**, **Fluss**, **Brett** und **Kameras**
brauchen wahrscheinlich einen alten Stand — fang mit den vier leichten an, das
Skript baut, was da ist.
