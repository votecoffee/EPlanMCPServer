"""Per-request cooperative checkpoints. These observations are not durable jobs or receipts."""

from __future__ import annotations

import contextvars
import threading
import uuid

import anyio

current = contextvars.ContextVar("eplan_operation", default=None)


class OperationCancelled(BaseException):
    """Stopped at an app checkpoint; prior units may already have committed."""


class Operations:
    def __init__(self):
        self.guard = threading.Lock()
        self.records = {}

    def start(self, name, context):
        hook = Hook(self, name, context)
        with self.guard:
            # Bound historical observations without evicting in-flight work.
            for key in list(self.records):
                if len(self.records) < 64:
                    break
                if self.records[key]["state"] not in {"queued", "running", "cancellation_requested"}:
                    del self.records[key]
            if len(self.records) >= 64:
                raise ValueError("Operation observation capacity is busy")
            self.records[hook.id] = {
                "id": hook.id,
                "operation": name,
                "state": "queued",
                "completed_units": 0,
                "total_units": None,
                "cancellation_requested": False,
                "worker_preempted": False,
            }
        return hook

    def snapshot(self):
        with self.guard:
            return {
                "scope": "This process only; not durable jobs or evidence of rollback",
                "items": [dict(r) for r in self.records.values()],
            }


class Hook:
    def __init__(self, owner, name, context):
        self.owner, self.context = owner, context
        self.id = uuid.uuid4().hex
        self.started = self.cancelled = False
        self.cancel_event = threading.Event()

    def request_cancel(self):
        self.cancel_event.set()
        self.update(state="cancellation_requested", cancellation_requested=True)

    def update(self, **values):
        with self.owner.guard:
            self.owner.records[self.id].update(values)

    def check(self):
        try:
            if self.cancel_event.is_set():
                raise OperationCancelled()
            anyio.from_thread.check_cancelled()
        except BaseException:
            self.cancelled = True
            self.update(state="cancellation_requested", cancellation_requested=True)
            raise

    def report(self, done, total, unit, message):
        self.update(completed_units=done, total_units=total, unit=unit, stage=message)
        if self.context is not None:
            try:
                anyio.from_thread.run(self.context.report_progress, done, total, message)
            except Exception:
                self.update(progress_delivery="unavailable; inspect structured operation status")

    def status(self):
        with self.owner.guard:
            return dict(self.owner.records[self.id])


def checkpoint():
    if hook := current.get():
        hook.check()


def progress(done, total, unit, message):
    if hook := current.get():
        hook.report(done, total, unit, message)
