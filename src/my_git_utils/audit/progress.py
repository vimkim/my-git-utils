"""Live audit progress on stderr, independent of the final stdout report."""

from __future__ import annotations

import math
import sys
from threading import Event, Lock, Thread
from time import monotonic

from .model import Repository


def duration(seconds: float) -> str:
    seconds = max(0, math.ceil(seconds))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


def readable(value: str) -> str:
    return value.translate({10: r"\n", 13: r"\r", 9: r"\t", 27: r"\x1b"})


class Progress:
    def __init__(self, enabled: bool = True, total: int | None = None) -> None:
        self.enabled = enabled
        self.lock = Lock()
        self.stopped = Event()
        self.thread: Thread | None = None
        self.started = monotonic()
        self.audit_started = self.started
        self.discovery = "lazygit history and project roots"
        self.directories = 0
        self.candidates = 0
        self.total = total
        self.completed = 0
        self.active: dict[str, tuple[str, str, float]] = {}
        self.last_printed = 0.0
        self.stream = sys.stderr

    def __enter__(self) -> Progress:
        if self.enabled:
            self.emit(force=True)
            self.thread = Thread(target=self.heartbeat, daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.stopped.set()
        if self.thread:
            self.thread.join()
        self.emit(force=True)

    def heartbeat(self) -> None:
        while not self.stopped.wait(1):
            self.emit()

    def discovered(self, location: str, directories: int, candidates: int) -> None:
        with self.lock:
            self.discovery = readable(location)
            self.directories = directories
            self.candidates = candidates

    def scanning(self, total: int) -> None:
        with self.lock:
            self.total = total
            self.completed = 0
            self.active.clear()
            self.audit_started = monotonic()
        self.emit(force=True)

    def task(self, repository: Repository, detail: str) -> None:
        with self.lock:
            self.active[str(repository.common)] = (
                readable(repository.path.name),
                readable(detail),
                monotonic(),
            )

    def finished(self, repository: Repository) -> None:
        with self.lock:
            self.completed += 1
            self.active.pop(str(repository.common), None)
        self.emit()

    def emit(self, force: bool = False) -> None:
        if not self.enabled:
            return
        with self.lock:
            now = monotonic()
            if not force and now - self.last_printed < 1:
                return
            self.last_printed = now
            elapsed = duration(now - self.started)
            if self.total is None:
                message = (
                    f"Discovering: {self.directories:,} directories, "
                    f"{self.candidates} repository paths | elapsed {elapsed} | "
                    f"ETA unknown until discovery finishes | {self.discovery}"
                )
            else:
                remaining = self.total - self.completed
                if not remaining:
                    eta = "complete"
                elif any(now - began > 5 for _, _, began in self.active.values()):
                    eta = "ETA uncertain; slow check in progress"
                elif self.completed < 2:
                    eta = "ETA estimating"
                else:
                    estimate = (now - self.audit_started) / self.completed * remaining
                    eta = f"ETA ~{duration(estimate)} (rough)"
                message = (
                    f"Scanning {self.completed}/{self.total} repositories | "
                    f"elapsed {elapsed} | {eta}"
                )
                if self.active:
                    active = "; ".join(
                        f"{name}: {detail} ({duration(now - began)})"
                        for name, detail, began in self.active.values()
                    )
                    message += f" | active: {active}"
                queued = remaining - len(self.active)
                if queued > 0:
                    message += f" | queued: {queued}"
            print(f"git-unsynced: {message}", file=self.stream, flush=True)
