# Retention editing for YouTube

Read this when the brief is "a YouTube video that holds the viewer", not just
"cut these takes together". It covers the editing decisions that move retention
and the external tools that plug into the video-use pipeline to make them.

Nothing here overrides `SKILL.md`. The Hard Rules still hold — in particular,
none of the pacing advice below justifies a cut tighter than the 30–200ms
padding window (Hard Rule 7).

## What actually moves retention

Retention is decided by the shape of the edit, not by effects. Four things
matter, roughly in order of impact:

**1. The first 15 seconds.** The largest single drop in any YouTube retention
graph is the opening. What survives it is a concrete promise the viewer can
evaluate immediately — the result, the surprise, the stake — delivered before
any intro, logo, or self-introduction. Cut the greeting. If the best sentence
in the video is at 4:12, the opening is a 3-second cold-open of that sentence.

**2. No dead air, anywhere.** Every pause that isn't doing dramatic work is a
place a viewer leaves. This is the mechanical half of the edit and the part
`helpers/autocut.py` automates: silence, filler words, false starts, the breath
before a sentence restarts. Removing it is not a style choice.

**3. Pattern interrupts on a rhythm.** Something must change visually roughly
every 5–15 seconds: a cut to b-roll, a zoom push, an on-screen graphic, an
angle change. The cadence matters more than the specific device. A static
talking head with no visual change past ~20 seconds is where the graph slopes.

**4. Open loops and payoff.** State a question early, answer it late. The
retention graph shows the answer landing as a flat section. A video that
resolves its premise at 40% has no reason to be watched at 60%.

Chapters, end screens and thumbnails matter too, but they are packaging — they
change who clicks, not who stays.

## Where each piece lands in the pipeline

| Stage | video-use does | External tool adds |
|---|---|---|
| Inventory | `transcribe_batch.py`, `pack_transcripts.py` | — |
| Dead space | `autocut.py` (auto-editor) | — |
| Take selection | editor sub-agent brief | — |
| Hook | manual: reorder EDL ranges, hook first | — |
| Pattern interrupts | `overlays` in the EDL | HyperFrames / Remotion / Manim |
| Captions | `render.py --build-subtitles` | — |
| Grade | `grade.py`, EDL `grade` field | — |
| Screen recording | — | OpenScreen |
| Repurposing to Shorts | — | AI-Youtube-Shorts-Generator |
| Manual fixes | — | LosslessCut |
| Finishing in an NLE | — | OpenTimelineIO |

## The tool stack

Install these lazily — only when a project actually needs one. None is a
dependency of the core pipeline.

### Already wired

- **[auto-editor](https://github.com/WyattBlue/auto-editor)** — silence and
  dead-space detection. `pip install auto-editor`, then `helpers/autocut.py`.
  This is the single biggest mechanical win on raw talking-head footage;
  20–40% removed is typical on unrehearsed takes.

- **[HyperFrames](https://github.com/heygen-com/hyperframes)** — HTML/CSS/GSAP
  → video. The default for overlay slots: lower thirds, callouts, kinetic text,
  stat cards. Fastest path for anything that is essentially a styled web page
  in motion. Needs Node.js 22+.

- **[Remotion](https://github.com/remotion-dev/remotion)** — React → video.
  Reach for it over HyperFrames when the animation is driven by data or needs
  real component composition across many similar slots.

- **[Manim](https://www.manim.community/)** — explanatory diagrams, math,
  step-by-step visual reasoning. `skills/manim-video/` is vendored in this repo;
  read its SKILL.md before building a Manim slot.

### Worth adding per project

- **[OpenScreen](https://github.com/getopenscreen/openscreen)** — screen
  recording with automatic zoom-to-cursor and smooth cursor motion. For
  tutorials and product demos this is itself a pattern-interrupt generator:
  the zoom pushes give the visual change that raw screen capture lacks.

- **[AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator)**
  — takes the finished `final.mp4` and cuts vertical 9:16 clips with highlight
  detection and auto-crop. Run it *after* the main edit, on the render, not on
  the raw sources.

- **[LosslessCut](https://github.com/mifi/lossless-cut)** — trims the rendered
  output without re-encoding. The right tool when the user wants "just take 4
  seconds off the front" and a re-render would cost minutes and a generation of
  quality.

- **[OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO)**
  — converts an EDL into a timeline Premiere or DaVinci Resolve can open. The
  escape hatch when the user wants to finish by hand; the agent's cut becomes
  the starting timeline instead of being thrown away.

- **[Waifu2x-Extension-GUI](https://github.com/AaronFeng753/Waifu2x-Extension-GUI)**
  — upscaling (Real-ESRGAN) and frame interpolation (RIFE). Only for genuinely
  low-resolution archive footage or deliberate slow-motion. Do not run it over
  good source material.

## Practical recipes

**Cold-open hook.** After `autocut.py`, read `takes_packed.md` and pick the
strongest sentence in the video regardless of position. Make it EDL range 0.
Follow it with the actual opening. The hook range and its later in-context
occurrence can both stay in — the repeat reads as a callback, not an error.

**Interrupt cadence.** With the EDL drafted, list `start_in_output` for every
overlay and check the gaps. A gap over ~15 seconds with no cut and no overlay
is where the graph slopes; that is the place to add a slot, not wherever an
animation seemed fun to build.

**Captions are not optional.** A large share of YouTube viewing is muted or
partially attended. `render.py --build-subtitles` applies the 2-word UPPERCASE
style; the `MarginV=90` safe-zone rule in `render.py` exists for vertical
platforms and should not be lowered without a specific reason.

**Grade last, and lightly.** A consistent grade reads as production value; an
aggressive one reads as a filter. `grade.py`'s `auto` mode per segment is the
safe default when takes were shot under varying light.

## What this cannot do

No editing decision makes a video go viral. Retention editing keeps the viewers
that the title and thumbnail already brought in — it raises the ceiling of a
video whose premise is worth watching, and does not create that premise. If the
material has no clear promise, the fix is another take, not another overlay.
