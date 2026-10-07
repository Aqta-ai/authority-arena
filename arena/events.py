"""The run's event stream: one ordered list, read live over SSE or replayed from a file."""
from __future__ import annotations

import threading
import time
from typing import Any


class EventLog:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._cond = threading.Condition()
        self._t0 = time.monotonic()
        self.closed = False

    def emit(self, type: str, **data: Any) -> dict[str, Any]:
        with self._cond:
            ev = {"seq": len(self.events), "t": int((time.monotonic() - self._t0) * 1000), "type": type, **data}
            self.events.append(ev)
            self._cond.notify_all()
            return ev

    def close(self) -> None:
        with self._cond:
            self.closed = True
            self._cond.notify_all()

    def wait_since(self, seq: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Events with seq >= `seq`, waiting up to `timeout` seconds for the first one."""
        with self._cond:
            if len(self.events) <= seq and not self.closed:
                self._cond.wait(timeout)
            return self.events[seq:]

    def of_type(self, *types: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] in types]
