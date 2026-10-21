"""Bounded request scheduling and crash-releasing, cross-process resource locks."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import threading
import time
from functools import partial
from pathlib import Path

import anyio


class ResourceBusy(ValueError):
    pass


class Coordinator:
    def __init__(self, state: Path, timeout: float = 180, workers: int = 4, oda_workers: int = 1):
        self.folder = state / "locks"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.timeout, self.workers, self.oda_workers = timeout, workers, oda_workers

    def _try(self, resource):
        path = self.folder / (hashlib.sha256(resource.encode()).hexdigest() + ".lock")
        stream = path.open("a+b")
        if path.stat().st_size == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EBUSY}:
                raise
            return None
        return stream

    @staticmethod
    def _release(stream):
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    @contextlib.contextmanager
    def lock(self, resource: str, timeout: float | None = None):
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while (stream := self._try(resource)) is None:
            if time.monotonic() >= deadline:
                raise ResourceBusy("Resource is busy; lock wait budget expired")
            time.sleep(0.025)
        try:
            yield
        finally:
            self._release(stream)

    @contextlib.contextmanager
    def pool(self, name: str, count: int):
        deadline = time.monotonic() + self.timeout
        stream = None
        while stream is None:
            for index in range(count):
                stream = self._try(f"pool:{name}:{index}")
                if stream is not None:
                    break
            if stream is None:
                if time.monotonic() >= deadline:
                    raise ResourceBusy("Worker capacity is busy; wait budget expired")
                time.sleep(0.025)
        try:
            yield
        finally:
            self._release(stream)

    @contextlib.contextmanager
    def worker(self, native=False):
        # Always acquire the backend before a general slot, so queued native work does not occupy all slots.
        with self.pool("oda", self.oda_workers) if native else contextlib.nullcontext():
            with self.pool("workers", self.workers):
                yield


class RequestScheduler:
    def __init__(self, workers=4, queued=32):
        self.workers, self.queued = workers, queued
        self.limiter = anyio.CapacityLimiter(workers)
        self.controls = anyio.CapacityLimiter(2)
        self.guard = threading.Lock()
        self.pending = self.active = self.pending_controls = self.completed = self.rejected = 0

    def status(self):
        with self.guard:
            return {
                "max_active_requests_per_process": self.workers,
                "max_queued_requests_per_process": self.queued,
                "active": self.active,
                "queued": self.pending - self.active,
                "control_requests": self.pending_controls,
                "completed": self.completed,
                "rejected": self.rejected,
                "scope": "Per server process; extraction worker slots and resource locks are shared by state directory",
            }

    async def run(self, fn, *args, control=False, **kwargs):
        with self.guard:
            count = self.pending_controls if control else self.pending
            if count >= (8 if control else self.workers + self.queued):
                self.rejected += 1
                raise ResourceBusy("Request queue is full; retry after checking any write request ID")
            if control:
                self.pending_controls += 1
            else:
                self.pending += 1

        def invoke():
            if not control:
                with self.guard:
                    self.active += 1
            try:
                return fn(*args, **kwargs)
            finally:
                if not control:
                    with self.guard:
                        self.active -= 1

        try:
            # A disconnected caller does not abandon a running state mutation. Its durable receipt remains queryable.
            return await anyio.to_thread.run_sync(
                partial(invoke), abandon_on_cancel=False, limiter=self.controls if control else self.limiter
            )
        finally:
            with self.guard:
                if control:
                    self.pending_controls -= 1
                else:
                    self.pending -= 1
                self.completed += 1
