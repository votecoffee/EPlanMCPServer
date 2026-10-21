"""Durable per-operation receipts and cross-process idempotency for app-state writes."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sqlite3
import time
import uuid

from .coordination import ResourceBusy


class Transactions:
    def __init__(self, state, coordinator):
        self.path = state / "requests.sqlite3"
        self.coordinator = coordinator
        with coordinator.lock("request-schema"):
            with self.database() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, operation TEXT NOT NULL, "
                    "fingerprint TEXT NOT NULL, state TEXT NOT NULL, started REAL NOT NULL, updated REAL NOT NULL, "
                    "result TEXT, error TEXT)"
                )

    @contextlib.contextmanager
    def database(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def validate(request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id):
            raise ValueError(
                "request_id must contain 1..128 letters, digits, underscore, dot, colon or hyphen"
            )

    def row(self, request_id):
        with self.database() as db:
            result = db.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
        return dict(result) if result else None

    def get(self, request_id, include_result=False):
        self.validate(request_id)
        row = self.row(request_id)
        if row is None:
            return {"request_id": request_id, "state": "not_found"}
        if row["state"] == "running":
            try:
                with self.coordinator.lock("request:" + request_id, timeout=0):
                    row = self.row(request_id)
                    if row["state"] == "running":
                        row["state"] = "unknown"
                        row["error"] = (
                            "The execution owner no longer holds its lock; inspect effects before a new request"
                        )
            except ResourceBusy:
                pass
        result = {
            k: row[k]
            for k in ("request_id", "operation", "state", "started", "updated", "fingerprint", "error")
        }
        if include_result and row.get("result"):
            result["result"] = json.loads(row["result"])
        result["scope"] = (
            "One operation; index batches commit per file. Native UI effects are not rollback transactions."
        )
        return result

    def execute(self, request_id, operation, arguments, fn):
        request_id = "request_" + uuid.uuid4().hex if request_id is None else request_id
        self.validate(request_id)
        fingerprint = hashlib.sha256(
            json.dumps(
                {"operation": operation, "arguments": arguments},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        with self.coordinator.lock("request:" + request_id):
            previous = self.row(request_id)
            if previous:
                if previous["operation"] != operation or previous["fingerprint"] != fingerprint:
                    raise ValueError("request_id conflicts with different operation arguments")
                if previous["state"] == "running":
                    with self.database() as db:
                        db.execute(
                            "UPDATE requests SET state='unknown',updated=?,error=? WHERE request_id=?",
                            (
                                time.time(),
                                "Previous execution lost ownership; outcome requires inspection",
                                request_id,
                            ),
                        )
                    previous = self.row(request_id)
                if previous.get("result"):
                    result = json.loads(previous["result"])
                    return {**result, "transaction": self.receipt(previous, replayed=True)}
                raise ValueError(
                    f"Request {request_id} is {previous['state']}: {previous.get('error')}; it was not re-executed"
                )
            now = time.time()
            with self.database() as db:
                db.execute(
                    "INSERT INTO requests VALUES(?,?,?,?,?,?,?,?)",
                    (request_id, operation, fingerprint, "running", now, now, None, None),
                )
            try:
                result = fn()
                encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
                if len(encoded.encode("utf-8")) > 185_000:
                    raise ValueError(
                        "Write result exceeds receipt budget; inspect app state before issuing a new request"
                    )
                state = (
                    "unknown"
                    if result.get("status") == "unknown"
                    else "failed"
                    if result.get("status") == "failed"
                    else "succeeded"
                )
            except BaseException as error:
                state = "failed" if isinstance(error, Exception) else "unknown"
                with self.database() as db:
                    db.execute(
                        "UPDATE requests SET state=?,updated=?,error=? WHERE request_id=?",
                        (state, time.time(), str(error)[:3000], request_id),
                    )
                raise
            with self.database() as db:
                db.execute(
                    "UPDATE requests SET state=?,updated=?,result=?,error=? WHERE request_id=?",
                    (
                        state,
                        time.time(),
                        encoded,
                        result.get("error") if state != "succeeded" else None,
                        request_id,
                    ),
                )
            return {**result, "transaction": self.receipt(self.row(request_id), replayed=False)}

    @staticmethod
    def receipt(row, replayed):
        return {k: row[k] for k in ("request_id", "operation", "state", "started", "updated")} | {
            "replayed": replayed
        }
