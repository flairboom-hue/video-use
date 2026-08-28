# AI Video Editor

A local, privacy-first video editor with an AI assistant. Drop a video in, it
does the mechanical editing, asks you only where a creative decision is needed,
and exports for YouTube, Shorts, Reels and TikTok.

Nothing is uploaded anywhere. Every stage runs on your machine.

```
INPUT/video.mp4
   → analysis (probe · proxy · scenes · transcript)
   → rough cut (silence · fillers · repetitions · false starts)
   → creative suggestions  ──► you decide
   → graphics · captions · loudness · reframe
   → preview → quality control → OUTPUT/
```

## Status — read this first

This is a working MVP, not a finished product. What is listed under
**Implemented** genuinely works end to end; what is under **Not built yet** is
absent rather than faked. There are no dead buttons and no stubbed stages: a
stage whose dependency is missing reports `unavailable` with the command that
fixes it, and the pipeline continues with what it can still do.

### Implemented and verified

| Area | What works |
|---|---|
| Import | Drag & drop, `INPUT/` folder watch, ffprobe analysis, HDR detection, proxy generation |
| Rough cut | Silence (auto-editor), filler words, repeated takes, false starts — with cut-safety rules |
| Scenes | PySceneDetect shot boundaries |
| Transcript | WhisperX, word-level timestamps, SRT + VTT export |
| Suggestions | Numbers, comparisons, lists, timelines, places → anchored proposals with a reason |
| Comparisons | Before/after wipes from two stills or two clips, anchored to a spoken word |
| Graphics | 10 animated types (number, vertical and horizontal bars, pie/donut, comparison, stat card, icon row, linked meters, lower third, kinetic type) in 4 themes, rendered with alpha, eased, caption-safe |
| Captions | 4 styles incl. per-word karaoke highlighting, correct output-timeline offsets |
| Render | Segment extract → lossless concat → overlays (PTS-shifted) → captions last → −14 LUFS |
| Aspects | 16:9, 9:16, 1:1, 4:5 — video cropped to fill, overlays fitted so they stay intact |
| Review | Per-proposal accept / change / reject, plus bulk actions by kind or confidence |
| Chat | Deterministic command parser; optional Ollama for anything beyond it |
| Versioning | Copy-on-write snapshots, restore any version |
| Quality control | Black frames, loudness, resolution, duration drift, caption sync, missing assets |
| Export | Per-platform folders, QC gate, sidecar SRT + project JSON |

### Not built yet

- **Face-tracked reframing.** The crop is centred. `engine/render.py` accepts a
  tracking curve and compiles it into the crop expression, but nothing produces
  that curve yet — MediaPipe would be the next step. A centred crop is fine for
  a single talking head and wrong for a two-shot.
- **Semantic B-roll matching.** Suggestions match B-roll by filename only. A
  real embedding index over `ASSETS/broll/` is the obvious upgrade; pretending
  keyword matching is semantic search would be the kind of fake capability this
  project avoids.
- **Timeline editing by drag.** The timeline renders the real state but is
  read-only. Edits go through the chat, the suggestion cards or the bulk
  actions.
- **Music ducking and EQ.** Loudness normalisation is implemented; sidechain
  ducking is not.
- **Smart zoom / punch-in.** Not implemented.
- **Speaker diarization in the UI.** WhisperX can produce it (`--diarize`,
  needs `HF_TOKEN`); nothing in the interface uses it yet.

## Graphic themes

A graphic composites onto whatever the camera shot, so its own palette is only
half the problem: white type on a bright kitchen wall is invisible however good
the colours are. Two mechanisms solve that, and each theme picks one.

| Theme | Mechanism | Use when |
|---|---|---|
| `light_card` *(default)* | Bright card behind the content, dark type | The common explainer look. Readable over anything. |
| `soft_light` | Pale card, muted blues, thinner type | Corporate or calm register |
| `bold_outline` | No card, heavy contour on type **and** shapes | Short-form; survives on any footage |
| `dark_minimal` | Neither — assumes dark or busy footage | Cinematic pieces shot dark |

`dark_minimal` is the one to avoid on bright material: it is the only theme
without a plate or a contour, and it washes out on a light wall.

Set it per project in the toolbar, or in the chat: *"nimm bold_outline"*.

## Motion blur

Rendered by temporal supersampling: each output frame is the average of
several sub-frames spanning the open shutter, in premultiplied alpha so moving
edges do not pick up a dark fringe. That is what a shutter physically does; a
directional blur applied afterwards cannot know which pixels were moving or
how fast.

| Level | Samples | Render cost |
|---|---|---|
| `off` *(default)* | — | 1× |
| `light` | 8 | ~7× |
| `normal` | 16 | ~13× |
| `heavy` | 24 | ~20× |

Sub-frames are stratified and jittered with a seeded hash, so a fast move
smears smoothly instead of showing countable arcs, and re-rendering the same
graphic produces byte-identical output.

**Where it actually helps is narrow.** These animations are deliberately slow
and eased, so on a number counting up or a bar growing, blur changes a few
hundred pixels and costs you seven times the render. It earns its keep on fast
motion — a whip-in, a swipe, a spin. Default is off for that reason; turn it on
per project when the movement is quick enough to strobe without it.

## The card's shadow

A soft lift under the plate, on by default in the two themes that have a
plate. It is separation that does not depend on the footage: measured over a
background almost as light as the card itself, the edge contrast goes from 28
to 66. Over dark footage it changes almost nothing, which is correct — there
the card already separates itself, and a shadow you can notice is one that is
too strong.

Two things were tried and rejected by looking at them:

- **A hairline contour.** Reads as a border, and the card stops looking like a
  card sitting on the picture and starts looking like a box drawn on top of
  it. Contour plus shadow is worse than either.
- **Concentric rounded rectangles instead of a blur.** Five times faster, and
  wrong: ImageDraw replaces pixels rather than blending them, so the rings
  overwrite each other into a hard dark border instead of accumulating into a
  gradient. The blur is real, and cached on its geometry — the card usually
  does not move, so it is paid once per graphic rather than once per frame.

Type has a floor tied to the output frame, not to the band. Without it a 0.028
label inside a 42% band is 13 px on a 1080p frame, which is gone on a phone.
It never grows type that was already big enough: with and without the floor,
every centred graphic renders byte-identical.

## Pace, and how a graphic lands

Two settings, because they are the two things that make an animation feel
slow. Both default to what the set was built with, so nothing moves unless you
ask.

| Pace | reveal / hold | A four-figure stat card |
|---|---|---|
| `calm` *(default)* | 0.90 / 1.00 | 1.87 s |
| `brisk` | 0.65 / 0.75 | 1.33 s |
| `quick` | 0.45 / 0.55 | 0.93 s |

Pace scales the staggers too, not just the hold. The stagger constants were
hand-tuned against the default reveal, so leaving them absolute would end the
graphic sooner without ever making the entrance quicker — the flat second at
the end would just be cut short.

`easing` is `smooth` (default) or `spring`. Spring overshoots by about 10% and
settles, which is what reads as snap.

**It never touches a value.** A bar that overshoots is longer than its own
measurement; a counter that overshoots displays a figure the data does not
contain. So `number_animation`, `bar_chart`, `bar_chart_h`, `pie_chart` and
`comparison` ignore the setting entirely and render identically under both —
asserted by a test, not by convention. Only `stat_card`, `icon_row` and
`text_animation` spring, and only in their position: opacity is driven off a
second curve that cannot exceed full.

## Where a graphic sits

A card is a full-width plate — 6% to 94% of the frame — over the vertical
middle. Over gameplay that is the strongest place for it. Over a talking head
it lands on the face, and no amount of reframing helps, because the plate is
wider than the shot.

`placement` re-lays the graphic into a band instead of moving it:

| | |
|---|---|
| `center` *(default)* | the whole frame, as before |
| `top` | a band at the top — the speaker stays visible underneath |
| `bottom` | a band above the caption zone, never behind it |

The band gets its own layout rather than a scaled copy of the centred one:
scaling a finished frame down to a third of its height softens every glyph,
and a slightly blurry graphic reads as a mistake. Type in a band is smaller
because it was laid out smaller.

Per project in the toolbar, or per graphic via `params.placement` on accept.

## Checking the room before you record

The rough cut rests on one assumption: that pauses are quieter than speech. In
a room with a fan, traffic or a loud machine that stops being true, auto-editor
finds no silence, and the cut removes nothing. Without a check you discover
that after forty minutes of recording rather than after one.

    python scripts/tontest.py probe.mp4

Sixty seconds of talking with real pauses is enough. It reports the share of
silence, the segment count and the longest gap, and says plainly whether the
room works — it judges nothing about the microphone or the voice, only the one
question the tool can actually answer.

## Before/after

`engine/compare.py` builds a wipe: both states in the same screen position,
with a divider travelling across. Side by side is the obvious layout and the
weak one — the eye has to travel between two frames and hold the first in
memory, so a texture that is slightly too bright or a shadow that is missing
simply does not register. A wipe puts the difference where the viewer is
already looking.

Either side may be a still or a clip, because most "before" states only exist
as a screenshot somebody happened to take. Each side is read through its own
hold and the shared sweep; the seam position is one expression, shared by the
wipe and the divider, so the line cannot drift off the seam.

Placement follows the same rule as graphics: anchored to a spoken word, so it
survives a re-cut. Without a transcript there is nothing to anchor against, and
the API says so and asks for a timestamp instead rather than rendering a clip
the renderer would then drop in silence.

    POST /api/projects/{id}/comparisons
    {"before": "broll/berge_vorher.png", "after": "broll/berge_nachher.png",
     "anchor_word": "Berge"}

Paths are resolved inside `ASSETS/` and nowhere else. `GET /api/assets` lists
what is there, and the toolbar's *Vorher/Nachher* button picks from that list —
a path the user has to spell correctly is a path they get wrong, and the
mistake would only surface after a render.

## Long-form or shorts?

Long-form first. The defaults are 16:9 and a YouTube export; vertical is a
secondary output derived from the same cut, not the other way round. Nothing in
the pipeline assumes a short clip.

What that costs in practice, measured on a 4-core machine with **no GPU** —
a 10-minute 1080p source:

| Stage | Time | Note |
|---|---|---|
| Probe | 0.3 s | |
| Proxy | 77 s | decode-bound; a GPU or a shorter source scales this down |
| Scenes | 13 s | runs on the proxy, not the source |
| Rough cut | 0.7 s | auto-editor is fast even on long files |
| **Analysis total** | **~92 s** | roughly 1/6 of runtime |

Transcription is the variable: WhisperX on CPU is slower than realtime, on a
GPU roughly 10× faster than realtime. For anything over ~20 minutes a GPU is
the difference between minutes and an afternoon.

Rendering scales linearly with the *output* length, not the source, so the
rough cut pays for itself twice: shorter video and shorter render. Measured on
the same machine, the 398 s cut of that 10-minute file:

| Step | Preview (960×540) | Final (1920×1080, CRF 20) |
|---|---|---|
| Extract 30 segments | 80 s | 193 s |
| Concat + composite | <1 s | 1 s |
| Loudness normalisation | 31 s | 33 s |
| **Total** | **111 s** | **227 s** |
| vs. realtime | 0.28× | 0.57× |

Both finish faster than the video plays, and QC passed every check on both
(−14.0 LUFS, no black frames, duration within 0.04 s of plan, correct
resolution). First preview of a 10-minute source is about three and a half
minutes of machine time; the final 1080p master another four. Transcription is
extra and is the one stage that wants a GPU.

Practically: a 10-minute video is a coffee break, a 40-minute one is more like
half an hour of machine time on a laptop with no GPU — unattended, since the
review step sits in the middle and waits for you anyway.

Two things are tuned for length rather than fixed:

- The suggestion budget follows runtime (about one proposal per 90 seconds,
  held between 6 and 40) instead of a flat cap that would starve a 40-minute
  talk and flood a 2-minute one.
- Analysis passes read the proxy, so source resolution barely affects them.

Past roughly forty minutes of source the review step becomes the bottleneck
rather than the machine, which is what the bulk actions above the suggestion
list are for: accept all graphics, accept everything above 75 % confidence, or
reject the lot — each one a single undoable version.

## Install

```bash
./install.sh          # macOS / Linux
.\install.ps1         # Windows
```

The installer checks Python ≥ 3.10 and ffmpeg, creates a virtualenv, installs
the Python packages, and stops with the exact install command if ffmpeg is
missing. It is idempotent — anything already present is detected and skipped.

Then:

```bash
./start.sh            # → http://127.0.0.1:8000
.\start.ps1
```

### Optional components

Both degrade gracefully. The app runs without them and says so in the UI.

```bash
pip install whisperx          # transcript → captions, filler removal, suggestions
                              # large download; a CUDA GPU makes it ~10× faster
```

Ollama for open-ended chat: <https://ollama.com>, then `ollama pull llama3.1`.
Without it the chat still handles the common commands through a deterministic
parser — the model only widens what can be phrased.

## Which open-source projects this uses, and why

| Project | Licence | Why this one |
|---|---|---|
| [FFmpeg](https://github.com/FFmpeg/FFmpeg) | LGPL/GPL | The only realistic foundation. Every filter used here — grade, tonemap, loudnorm, subtitles, overlay — is native, so there is no second rendering engine to keep in sync. |
| [auto-editor](https://github.com/WyattBlue/auto-editor) | Unlicense | The largest mechanical win on unrehearsed footage: 20–40 % of runtime removed. Its `v1` export is the most stable of its formats, which is what this integrates against. |
| [WhisperX](https://github.com/m-bain/whisperX) | BSD-2 | Word-level timestamps plus diarization. Phrase-level ASR would break the rough cut, the caption animation and the overlay anchoring at once. |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | BSD-3 | Gepflegt since 2014, does one thing reliably. Used for shot boundaries and B-roll indexing. |
| [Pillow](https://github.com/python-pillow/Pillow) | MIT-CMU | Chosen over Remotion for the graphics. Remotion needs Node plus a per-project `npm install` and renders in a headless browser — the most fragile step in a local install. Pillow is already a dependency and renders deterministically. The trade-off is a smaller shape vocabulary, which is the right trade for something that has to run on the user's machine. |
| [FastAPI](https://github.com/fastapi/fastapi) | MIT | REST + WebSocket in one process, no broker. |
| [Ollama](https://github.com/ollama/ollama) | MIT | Local LLM behind a swappable interface. Optional by design. |

**Deliberately not used:** Remotion (source-available, not OSI — free for
individuals and teams up to three, paid above that; and the Node dependency),
OpenMontage (AGPL-3.0 and only months old), Celery/Redis (a broker to install
for a single-user local app).

## Project structure

```
ai-video-editor/
├── engine/                 pure logic, no web framework
│   ├── capabilities.py     what this machine can do, probed honestly
│   ├── media.py            ffprobe facts, proxy, thumbnails
│   ├── scenes.py           PySceneDetect
│   ├── transcribe.py       WhisperX → the shared transcript format
│   ├── rough_cut.py        the four removal passes + safety rules
│   ├── suggestions.py      where visual support would help
│   ├── graphics.py         animated overlays (PIL → ffmpeg)
│   ├── captions.py         styled ASS, karaoke timing
│   ├── render.py           the compositor
│   ├── qc.py               pre-export checks
│   ├── project.py          non-destructive project file + versions
│   ├── pipeline.py         stage orchestration
│   └── llm.py              swappable LLM + deterministic command parser
├── backend/
│   ├── main.py             FastAPI: REST, WebSocket, static
│   ├── jobs.py             one worker, explicit status machine
│   └── watcher.py          INPUT/ folder watch
├── frontend/index.html     single file, no build step
├── tests/                  59 tests, pure logic, < 1s
├── INPUT/  OUTPUT/  ASSETS/  projects/  config/
├── install.sh / install.ps1
└── start.sh / start.ps1
```

`projects/<id>/project.json` is the single source of truth. The source video is
opened read-only and never rewritten; rendering produces a new file. Undo is a
file copy, not an inverse-operation replay.

## Troubleshooting

**"ffmpeg — required" and the app will not start.**
`brew install ffmpeg` / `sudo apt-get install ffmpeg` / `winget install Gyan.FFmpeg`.
On Windows open a new terminal afterwards so PATH is picked up.

**Transcript stage says `unavailable`.**
WhisperX is not installed. `pip install whisperx`. Everything else still runs;
you lose captions, filler removal and creative suggestions.

**WhisperX fails with a CUDA error.**
Set `device=cpu`. The app already falls back to CPU automatically when no GPU
is detected; this only bites when a GPU exists but the CUDA runtime is broken.

**Transcription is very slow.**
No GPU. `engine/capabilities.py` drops to a smaller Whisper model on modest
machines; force it further with a smaller model if needed.

**Export is blocked by quality control.**
Read the finding — it names the problem and the remedy. Re-run with
`{"force": true}` to override deliberately. A file that fails QC is deleted
rather than shipped.

**A graphic lands on the wrong sentence.**
It should not: overlays are anchored to a spoken word, not a timestamp, and
re-resolved on every render. If the anchored word was cut out, the overlay is
dropped rather than misplaced.

**The chat does not understand me.**
Without Ollama it recognises a fixed set of commands (trim, caption size and
style, remove overlays, aspect, grade, make short). Install Ollama for the rest.

**A file in `INPUT/` was not picked up.**
The watcher waits until the file size stops changing, so a large copy is not
imported half-written. Give it a few seconds.

## Tests

```bash
pytest
```

59 tests over the pure logic — no ffmpeg, no models, no network, under a
second. They target the rules that fail *silently*: caption timeline offsets,
cut-safety thresholds, suggestion restraint, non-destructive versioning.
Verified against deliberate mutations rather than assumed to work.
