"""INPUT folder watch — drop a file in, get a project.

Polling rather than inotify: it is portable across Windows/macOS/Linux without
a dependency, and a 2-second interval is imperceptible for this use.

The stability check matters more than the interval. A large file copied into
the folder appears immediately but keeps growing; importing it mid-copy
produces a truncated project. A file is only picked up once its size has been
unchanged across two polls.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mts", ".m2ts"}


class InputWatcher:
    def __init__(self, folder: Path, on_new: Callable[[Path], None],
                 interval: float = 2.0):
        self.folder = Path(folder)
        self.on_new = on_new
        self.interval = interval
        self._seen: dict[str, int] = {}
        self._imported: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        # Anything already present at boot counts as seen, so restarting the
        # server does not re-import the whole folder.
        for p in self._candidates():
            self._imported.add(str(p))
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _candidates(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        return [p for p in self.folder.iterdir()
                if p.is_file() and p.suffix.lower() in VIDEO_EXTS]

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                for p in self._candidates():
                    key = str(p)
                    if key in self._imported:
                        continue
                    size = p.stat().st_size
                    if self._seen.get(key) == size and size > 0:
                        self._imported.add(key)
                        self._seen.pop(key, None)
                        self.on_new(p)
                    else:
                        self._seen[key] = size
            except Exception:
                # A watcher must never take the server down.
                continue
