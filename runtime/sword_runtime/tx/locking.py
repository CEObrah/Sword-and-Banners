"""Advisory single-writer lock for one campaign repository."""

import fcntl
import json
import os
import threading
import time
from pathlib import Path
from typing import IO, Optional

from sword_runtime.tx.errors import LockUnavailableError


class SingleWriterLock:
    """Exclusive POSIX file lock with a bounded acquisition timeout."""

    def __init__(
        self,
        path: object,
        timeout: float = 0.0,
        poll_interval: float = 0.05,
    ) -> None:
        if timeout < 0:
            raise ValueError("lock timeout must be non-negative")
        if poll_interval <= 0:
            raise ValueError("lock poll interval must be positive")
        self.path = Path(path)
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self._handle: Optional[IO[bytes]] = None

    @property
    def acquired(self) -> bool:
        return self._handle is not None

    def acquire(self) -> "SingleWriterLock":
        if self.acquired:
            raise RuntimeError("writer lock instance is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise LockUnavailableError(str(self.path), self.timeout)
                time.sleep(min(self.poll_interval, max(0.0, deadline - time.monotonic())))

        diagnostic = {
            "pid": os.getpid(),
            "thread": threading.get_ident(),
            "acquired_unix_ns": time.time_ns(),
        }
        handle.seek(0)
        handle.truncate()
        handle.write((json.dumps(diagnostic, sort_keys=True) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle
        return self

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> "SingleWriterLock":
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()

