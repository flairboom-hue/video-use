#!/usr/bin/env python3
"""Ein Bild pro Block: wie das Video aussehen soll.

Der Sinn ist nicht Hübschsein, sondern Nachrechnen. Die Grafiken in diesen
Bildern sind **die echten** — dieselben Generatoren, dieselbe Karte, dieselben
Ränder, dieselbe Untertitel-Schutzzone. Wenn eine Karte hier ein Gesicht
verdeckt, verdeckt sie es im fertigen Video auch.

Was Platzhalter ist, ist als Platzhalter gezeichnet: Spielaufnahmen und
Facecam gibt es noch nicht, also stehen dort flache Flächen mit einem
gestrichelten Rahmen. Nichts hier tut so, als wäre es Bildmaterial.

    python beispiele/pogo-gnom/storyboard.py [ziel-ordner]

Erzeugt die Einzelbilder und eine Übersicht mit allen Blöcken.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image, ImageDraw  # noqa: E402

from engine import graphics as gfx  # noqa: E402

W, H = 1920, 1080
THEME = "light_card"

# Aus engine/graphics.py — hier nur gespiegelt, um die Zone einzuzeichnen.
CAPTION_BAND = gfx.CAPTION_SAFE_BOTTOM

SKY = (126, 178, 224)
SKY_NIGHT = (34, 40, 66)
GRASS = (122, 174, 92)
DIRT = (150, 128, 96)
MOONDUST = (108, 108, 116)
ROOM = (74, 78, 92)
SKIN = (198, 160, 132)
SHIRT = (58, 66, 88)
GUIDE = (255, 255, 255, 70)
PLACEHOLDER_INK = (255, 255, 255, 120)


# ----------------------------------------------------------- Platzhalter ---

def _dashed_rect(draw, box, colour, dash=26, width=3):
    x0, y0, x1, y1 = box
    for x in range(int(x0), int(x1), dash * 2):
        draw.line([x, y0, min(x + dash, x1), y0], fill=colour, width=width)
        draw.line([x, y1, min(x + dash, x1), y1], fill=colour, width=width)
    for y in range(int(y0), int(y1), dash * 2):
        draw.line([x0, y, x0, min(y + dash, y1)], fill=colour, width=width)
        draw.line([x1, y, x1, min(y + dash, y1)], fill=colour, width=width)


def _marker(img, text, st):
    """Der Platzhalter-Hinweis, direkt über der Untertitelzone.

    Nicht oben links: dort sitzen bei der Wischblende die Beschriftungen, und
    zwei Texte übereinander liest niemand.
    """
    draw = ImageDraw.Draw(img, "RGBA")
    font = st.font(int(H * 0.022))
    tw, th = gfx._text_size(draw, text, font)
    x, y = 34, H * (1 - CAPTION_BAND) - th - H * 0.022
    draw.rounded_rectangle([x - 14, y - 8, x + tw + 14, y + th + 8],
                           radius=8, fill=(0, 0, 0, 130))
    draw.text((x, y), text, font=font, fill=PLACEHOLDER_INK)


def gnom(draw, cx, cy, scale=1.0, colour=(58, 62, 74)):
    """Zwerg auf Pogostick, als Silhouette. Genug, um ihn wiederzuerkennen."""
    s = scale
    draw.line([cx, cy + 40 * s, cx, cy + 150 * s], fill=colour, width=int(10 * s))
    draw.line([cx - 26 * s, cy + 150 * s, cx + 26 * s, cy + 150 * s],
              fill=colour, width=int(12 * s))
    draw.ellipse([cx - 30 * s, cy - 20 * s, cx + 30 * s, cy + 45 * s], fill=colour)
    draw.ellipse([cx - 22 * s, cy - 62 * s, cx + 22 * s, cy - 18 * s], fill=SKIN)
    draw.polygon([(cx - 30 * s, cy - 40 * s), (cx + 30 * s, cy - 40 * s),
                  (cx, cy - 112 * s)], fill=(186, 58, 44))


def spielaufnahme(img, note="SPIELAUFNAHME", night=False, gnom_at=(0.42, 0.52)):
    draw = ImageDraw.Draw(img, "RGBA")
    sky = SKY_NIGHT if night else SKY
    draw.rectangle([0, 0, W, H * 0.72], fill=sky)
    draw.rectangle([0, H * 0.72, W, H], fill=MOONDUST if night else GRASS)
    if night:
        draw.ellipse([W * 0.72, H * 0.10, W * 0.72 + 150, H * 0.10 + 150],
                     fill=(222, 224, 210))
    else:
        for cx, cy, r in ((W * 0.16, H * 0.16, 70), (W * 0.24, H * 0.14, 95),
                          (W * 0.78, H * 0.22, 80)):
            draw.ellipse([cx - r, cy - r * 0.6, cx + r, cy + r * 0.6],
                         fill=(255, 255, 255, 190))
    gnom(draw, W * gnom_at[0], H * gnom_at[1], 1.0)
    return draw, note


def facecam(img, note="FACECAM"):
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, 0, W, H], fill=ROOM)
    draw.rectangle([W * 0.06, H * 0.10, W * 0.34, H * 0.62], fill=(88, 92, 108))
    cx, cy = W * 0.5, H * 0.46
    draw.ellipse([cx - 210, cy + 150, cx + 210, cy + 700], fill=SHIRT)
    draw.ellipse([cx - 125, cy - 165, cx + 125, cy + 160], fill=SKIN)
    return draw, note


def bildschirm(img, note="TERMINAL / STEAMWORKS"):
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, 0, W, H], fill=(22, 24, 30))
    st = gfx.make_style(THEME, width=W, height=H)
    mono = st.font(int(H * 0.030))
    y = H * 0.16
    for text, colour in (("$ steamcmd +run_app_build ...", (150, 158, 172)),
                         ("Scanning content...", (150, 158, 172)),
                         ("Successfully finished build", (120, 210, 130)),
                         ("", (0, 0, 0)),
                         ("0 files found", (200, 120, 110))):
        if text:
            draw.text((W * 0.10, y), text, font=mono, fill=colour)
        y += H * 0.055
    return draw, note


def neutral(img, note="VOLLBILD-GRAFIK"):
    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([0, 0, W, H], fill=(46, 52, 62))
    return draw, note


# -------------------------------------------------------------- Grafiken ---

def grafik_frame(fn, *args, t=1.0, **kwargs) -> Image.Image:
    """Ein Einzelbild aus einem echten Generator, ohne ffmpeg.

    Die Generatoren rendern sonst eine ganze Sequenz und kodieren sie. Für ein
    Storyboard genügt der Endzustand — und weil es derselbe Zeichencode ist,
    stimmen Ränder, Kartenbreite und Schriftgrößen mit dem Video überein.
    """
    captured = {}

    def fake_render(frame, dur, st, out):
        captured["frame"] = frame
        return out

    real, gfx._render = gfx._render, fake_render
    try:
        fn(Path("unbenutzt.mov"), *args, **kwargs)
    finally:
        gfx._render = real

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    captured["frame"](ImageDraw.Draw(layer, "RGBA"), t, layer)
    return layer


def vergleich_frame(st, links="vorher", rechts="nachher") -> Image.Image:
    """Eine Wischblende, mitten im Lauf — schematisch, aber maßstäblich."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    seam = int(W * 0.55)

    left = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dl = ImageDraw.Draw(left, "RGBA")
    dl.rectangle([0, 0, W, H * 0.72], fill=(150, 196, 236))
    dl.rectangle([0, H * 0.72, W, H], fill=(150, 200, 120))
    dl.polygon([(W * 0.30, H * 0.42), (W * 0.52, H * 0.16), (W * 0.74, H * 0.42)],
               fill=(178, 168, 158))          # schwebender Berg
    img.paste(left.crop((0, 0, seam, H)), (0, 0))

    right = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(right, "RGBA")
    dr.rectangle([0, 0, W, H * 0.72], fill=(126, 178, 224))
    dr.rectangle([0, H * 0.72, W, H], fill=GRASS)
    dr.polygon([(W * 0.30, H * 0.72), (W * 0.52, H * 0.40), (W * 0.74, H * 0.72)],
               fill=(132, 122, 112))          # verankert
    img.paste(right.crop((seam, 0, W, H)), (seam, 0))

    draw = ImageDraw.Draw(img, "RGBA")
    draw.rectangle([seam - 5, 0, seam + 5, H], fill=(0, 0, 0, 140))
    draw.rectangle([seam - 2, 0, seam + 2, H], fill=(*st.accent, 255))

    font = st.font(int(H * 0.030))
    for text, side in ((links, "l"), (rechts, "r")):
        tw, th = gfx._text_size(draw, text.upper(), font)
        pad, margin = H * 0.020, H * 0.035
        x = margin if side == "l" else W - margin - tw - pad * 2
        draw.rounded_rectangle([x, margin, x + tw + pad * 2, margin + th + pad * 1.2],
                               radius=H * 0.010, fill=st.panel)
        draw.text((x + pad, margin + pad * 0.6), text.upper(), font=font,
                  fill=(*st.text, 255))
    return img


# ---------------------------------------------------------------- Blöcke ---

KARTE_OBEN = "Karte oben platziert — Gesicht bleibt frei"


def panels(st: gfx.Style) -> list[tuple[str, str, str, callable, str]]:
    """(Zeit, Blockname, Notiz, Zeichenfunktion, Konflikt) wie im Video.

    Das fünfte Feld ist ein Hinweis, kein Schmuck. Eine Grafikkarte ist eine
    Vollbreite-Platte und liegt normalerweise mittig — also genau dort, wo in
    einer Talking-Head-Einstellung der Kopf ist. Wo beides zusammenkommt, wird
    die Karte oben platziert (`placement="top"`), und das steht am Bild.
    """

    # Für die Blöcke, in denen das Gesicht mit im Bild ist: dieselbe Karte,
    # aber im oberen Band statt in der Mitte.
    oben = gfx.make_style(THEME, width=W, height=H, fps=st.fps,
                          reserve_caption_band=True, placement="top")

    def hook(img):
        d, n = spielaufnahme(img, "SPIELAUFNAHME · Sturz", gnom_at=(0.44, 0.30))
        return d, n

    def praemisse(img):
        d, n = facecam(img)
        img.alpha_composite(grafik_frame(
            gfx.stat_card,
            [("26 063", "Zeilen"), ("1", "Datei"), ("36", "Tage"), ("387", "Commits")],
            oben))
        return d, n

    def kapitel(img):
        d, n = spielaufnahme(img, "SPIELAUFNAHME", gnom_at=(0.50, 0.63))
        img.alpha_composite(grafik_frame(gfx.text_animation, "7 Fehler", st))
        return d, n

    def spiel(img):
        return spielaufnahme(img, "SPIELAUFNAHME · Aufstieg", gnom_at=(0.52, 0.38))

    def bescheide(img):
        d, n = spielaufnahme(img, "SPIELAUFNAHME · Bescheid")
        for i, off in enumerate((0.0, 0.04, 0.08)):
            x0, y0 = W * (0.30 + off), H * (0.18 + off)
            d.rectangle([x0, y0, x0 + W * 0.34, y0 + H * 0.46],
                        fill=(246, 244, 238), outline=(120, 116, 108), width=4)
        d.ellipse([W * 0.52, H * 0.46, W * 0.62, H * 0.56],
                  outline=(190, 54, 44), width=10)
        return d, n

    def physik(img):
        d, n = spielaufnahme(img, "SPIELAUFNAHME · Sprung", gnom_at=(0.87, 0.60))
        img.alpha_composite(grafik_frame(
            gfx.linked_meters, "Ladung",
            [("Höhe", 9.0, 15.0, ""), ("Weite", 3.0, 8.0, "")], st))
        return d, n

    def landefenster(img):
        d, n = neutral(img)
        img.alpha_composite(grafik_frame(gfx.bar_chart_h, [
            ("Rasen", 52), ("Blumenbeet", 40), ("Wolken", 31), ("Gartenweg", 29),
            ("Ast", 23), ("Dach", 22), ("Antenne", 13), ("Schnur", 12.4),
            ("Ballons", 10.9), ("Mond", 8.8), ("Ziel", 7.0),
        ], st, suffix=" %"))
        return d, n

    def fehler(img):
        d = ImageDraw.Draw(img, "RGBA")
        img.alpha_composite(vergleich_frame(st, "schwebend", "verankert"))
        return d, "VERGLEICH · zwei Screenshots"

    def gutes(img):
        d, n = spielaufnahme(img, "SPIELAUFNAHME · Garderobe", gnom_at=(0.88, 0.60))
        img.alpha_composite(grafik_frame(
            gfx.stat_card,
            [("8", "Figuren"), ("54", "Kosmetikteile"),
             ("7", "Sprachen"), ("251", "Kollisionsflächen")], st))
        return d, n

    def gestaendnis(img):
        return facecam(img, "FACECAM · groß, kein Schnitt")

    def steam(img):
        d, n = bildschirm(img)
        img.alpha_composite(grafik_frame(
            gfx.number_animation, 9, "Fehler in zwei Tagen", "", st))
        return d, n

    def bilanz(img):
        d, n = facecam(img)
        img.alpha_composite(grafik_frame(
            gfx.stat_card,
            [("36", "Tage"), ("387", "Commits"),
             ("26 063", "Zeilen"), ("9", "Fehler zuletzt")], oben))
        return d, n

    def abschluss(img):
        d, n = spielaufnahme(img, "SPIELAUFNAHME · Mond", night=True,
                             gnom_at=(0.50, 0.64))
        img.alpha_composite(grafik_frame(
            gfx.text_animation, "WISHLIST NOW", st))
        return d, n

    return [
        ("0:00", "Hook", "Kein Logo, kein Intro.", hook, ""),
        ("0:08", "Prämisse + KI-Frage", "Facecam und Karte gleichzeitig.",
         praemisse, KARTE_OBEN),
        ("0:45", "Kapitel „7 Fehler”", "Kurzer Übergang über dem Spielbild.", kapitel, ""),
        ("0:50", "Was das Spiel ist", "Erklären ohne Gesicht.", spiel, ""),
        ("1:20", "Drei Bescheide", "Drei nacheinander, rhythmisch.", bescheide, ""),
        ("1:45", "Pogo-Physik", "Ein Regler, zwei Balken.", physik, ""),
        ("2:30", "Landefenster", "Vollbild. Elf Zeilen brauchen Zeit.", landefenster, ""),
        ("2:45", "Die Fehler", "Links der Fehler, rechts die Behebung.", fehler, ""),
        ("5:15", "Was gut geworden ist", "Anderer Ton. Hier darf Freude rein.", gutes, ""),
        ("7:30", "Das Geständnis", "Groß, ruhig, unmontiert.", gestaendnis, ""),
        ("9:00", "Steam-Kapitel", "Bildschirmlastig.", steam, ""),
        ("10:20", "Bilanz", "Zurückblickend, nicht triumphierend.",
         bilanz, KARTE_OBEN),
        ("10:40", "Abschluss", "Kurz, dann Endkarte.", abschluss, ""),
    ]


# ----------------------------------------------------------------- Bauen ---

def draw_konflikt(img, st, text):
    """Ein Hinweisstreifen auf dem Bild selbst, nicht in der Bildunterschrift.

    Wer das Storyboard durchblättert, soll die besondere Stelle im Bild sehen
    und nicht erst darunter lesen müssen, warum sie besonders ist.
    """
    draw = ImageDraw.Draw(img, "RGBA")
    font = st.font(int(H * 0.026))
    tw, th = gfx._text_size(draw, text, font)
    pad = H * 0.016
    bar_h = th + pad * 2
    draw.rectangle([0, H - bar_h, W, H], fill=(*st.accent, 235))
    draw.text(((W - tw) / 2, H - bar_h + pad), text, font=font,
              fill=(255, 255, 255, 255))


def _fit(draw, text, font, max_w):
    """Text auf die Spaltenbreite kürzen — gemessen, nicht nach Zeichenzahl.

    Nach Zeichen zu kürzen ging schief: dieselben 64 Zeichen sind mal breiter
    als die Spalte und mal halb so breit, und der Überhang lief in die
    Nachbarspalte.
    """
    if gfx._text_size(draw, text, font)[0] <= max_w:
        return text
    while text and gfx._text_size(draw, text + "…", font)[0] > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def draw_guides(img, st, sample="… und genau da wird es interessant."):
    """Untertitelzone und Kartenrand einzeichnen — die zwei Linien, an denen
    sich im Schnitt entscheidet, ob etwas verdeckt wird."""
    draw = ImageDraw.Draw(img, "RGBA")
    band_top = H * (1 - CAPTION_BAND)
    draw.line([0, band_top, W, band_top], fill=GUIDE, width=3)
    font = st.font(int(H * 0.050))
    tw, th = gfx._text_size(draw, sample, font)
    x, y = (W - tw) / 2, band_top + (H * CAPTION_BAND - th) / 2
    draw.text((x, y), sample, font=font, fill=(255, 255, 255, 255),
              stroke_width=6, stroke_fill=(0, 0, 0, 210))


def build(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    st = gfx.make_style(THEME, width=W, height=H, fps=30,
                        reserve_caption_band=True)
    made = []

    for i, (zeit, name, notiz, fn, konflikt) in enumerate(panels(st), 1):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        draw, marker = fn(img)
        draw_guides(img, st)

        d = ImageDraw.Draw(img, "RGBA")
        _dashed_rect(d, (12, 12, W - 12, H - 12), (255, 255, 255, 55))
        _marker(img, marker, st)
        if konflikt:
            draw_konflikt(img, st, konflikt)

        path = out_dir / f"{i:02d}_{zeit.replace(':', '-')}_{_slug(name)}.png"
        img.convert("RGB").save(path)
        made.append(path)
        print(f"  {path.name:38} {zeit:>5}  {notiz}"
              + (f"   ↑ {konflikt}" if konflikt else ""))

    sheet = contact_sheet(made, panels(st), out_dir / "00_uebersicht.png", st)
    made.insert(0, sheet)
    return made


def _slug(text: str) -> str:
    keep = "abcdefghijklmnopqrstuvwxyz0123456789"
    swap = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", " ": "-"}
    out = "".join(swap.get(c, c) for c in text.lower())
    return "".join(c for c in out if c in keep + "-").strip("-")


def contact_sheet(paths, blocks, out: Path, st, cols=3, thumb_w=620) -> Path:
    """Alle Blöcke auf einem Blatt. Der Punkt ist der Rhythmus: sieht man
    dreizehn Bilder nebeneinander, fällt auf, wenn fünf davon gleich aussehen."""
    thumb_h = int(thumb_w * H / W)
    label_h = 92
    pad = 26
    rows = (len(paths) + cols - 1) // cols
    sheet_w = cols * thumb_w + (cols + 1) * pad
    sheet_h = rows * (thumb_h + label_h) + (rows + 1) * pad + 120

    sheet = Image.new("RGB", (sheet_w, sheet_h), (24, 26, 32))
    d = ImageDraw.Draw(sheet)
    title = st.font(52)
    d.text((pad, 40), "POGO GNOM — Storyboard", font=title, fill=(238, 238, 238))
    sub = st.font(28)
    d.text((pad, 100),
           "Grafiken echt · Spielaufnahme und Facecam sind Platzhalter",
           font=sub, fill=(150, 155, 165))

    zeit_f, name_f, note_f = st.font(30), st.font(30), st.font(24)
    for i, (path, (zeit, name, notiz, _, konflikt)) in enumerate(zip(paths, blocks)):
        r, c = divmod(i, cols)
        x = pad + c * (thumb_w + pad)
        y = 150 + pad + r * (thumb_h + label_h + pad)
        sheet.paste(Image.open(path).resize((thumb_w, thumb_h), Image.LANCZOS), (x, y))
        d.text((x, y + thumb_h + 12), zeit, font=zeit_f, fill=(255, 140, 60))
        d.text((x + 110, y + thumb_h + 12), _fit(d, name, name_f, thumb_w - 110),
               font=name_f, fill=(238, 238, 238))
        line = f"↑ {konflikt}" if konflikt else notiz
        colour = (255, 150, 80) if konflikt else (150, 155, 165)
        d.text((x, y + thumb_h + 50), _fit(d, line, note_f, thumb_w),
               font=note_f, fill=colour)

    sheet.save(out)
    print(f"\n  {out.name}  ({sheet_w}x{sheet_h})")
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("storyboard")
    print(f"POGO GNOM — Storyboard nach {target}/\n")
    built = build(target)
    print(f"\n{len(built) - 1} Blöcke + Übersicht.")
