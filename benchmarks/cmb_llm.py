"""Chat client with an adaptive request rate for shared gateways that return 429."""
from __future__ import annotations

import os
import threading
import time

from bench_llm import Chat


class ThrottledChat(Chat):
    """Serializes request starts and backs off when the gateway reports rate limiting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._interval = float(os.environ.get("CSM_BENCH_MIN_INTERVAL", "0.4"))
        self._successes = 0

    def _wait_slot(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval

        if slot > now:
            time.sleep(slot - now)

    def _slower(self) -> None:
        with self._lock:
            self._interval = min(3.0, self._interval * 1.6)

    def _faster(self) -> None:
        with self._lock:
            self._successes += 1
            if self._successes % 20 == 0:
                self._interval = max(0.1, self._interval * 0.92)

    def ask(self, system: str, user: str, **kwargs) -> str:
        last = None
        try:
            attempts = max(1, int(os.environ.get("CSM_BENCH_EMPTY_RETRIES", "8")))
        except ValueError:
            attempts = 8
        for attempt in range(attempts):
            self._wait_slot()
            try:
                text = super().ask(system, user, **kwargs)
                if not text.strip():
                    raise RuntimeError("empty content")
                self._faster()
                return text
            except RuntimeError as error:
                last = error
                message = str(error)
                if "empty content" in message:
                    time.sleep(1.0 + attempt)
                    continue
                if "429" in message:
                    self._slower()
                    time.sleep(min(30.0, 2.0 ** attempt))
                    continue
                raise
        raise RuntimeError(f"gateway kept failing: {last}")
