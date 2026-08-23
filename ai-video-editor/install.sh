#!/usr/bin/env bash
# One-shot installer. Everything it does is idempotent: already-installed
# components are detected and skipped, never reinstalled.
set -euo pipefail
cd "$(dirname "$0")"

ok(){ printf '  \033[32mok\033[0m   %s\n' "$1"; }
miss(){ printf '  \033[33mmiss\033[0m %s\n' "$1"; }
die(){ printf '  \033[31mfail\033[0m %s\n' "$1"; exit 1; }

echo "AI Video Editor — install"
echo

command -v python3 >/dev/null || die "Python 3.10+ is required. https://python.org"
PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)' \
  || die "Python $PYV found, 3.10+ required."
ok "Python $PYV"

if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ok "ffmpeg $(ffmpeg -version | head -1 | cut -d' ' -f3)"
else
  miss "ffmpeg — required"
  if   command -v brew    >/dev/null; then echo "    brew install ffmpeg"
  elif command -v apt-get >/dev/null; then echo "    sudo apt-get install -y ffmpeg"
  elif command -v pacman  >/dev/null; then echo "    sudo pacman -S ffmpeg"
  else echo "    https://ffmpeg.org/download.html"; fi
  die "install ffmpeg, then re-run"
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv && ok "created .venv"
else
  ok ".venv exists"
fi
PY=.venv/bin/python
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r requirements.txt
ok "python packages"

if "$PY" -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('auto_editor') or __import__('shutil').which('auto-editor') else 1)" 2>/dev/null; then
  ok "auto-editor"
else
  "$PY" -m pip install --quiet auto-editor && ok "auto-editor (installed)" || miss "auto-editor — silence detection will be skipped"
fi

echo
echo "Optional, not installed by default:"
echo "  WhisperX (transcription, captions, creative suggestions):"
echo "      $PY -m pip install whisperx        # large; pulls in torch"
echo "  Ollama (chat beyond the built-in commands):  https://ollama.com"
echo
[ -f .env ] || { cp .env.example .env && ok "created .env"; }
mkdir -p INPUT OUTPUT ASSETS/{broll,music,images,fonts,logos} projects config
ok "folders"
echo
echo "Done.  Start it with:  ./start.sh"
