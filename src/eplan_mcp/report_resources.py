"""Bounded, source-bound report views from the same private immutable snapshot store."""

import base64
import hashlib
import json
import re

from .exports import ExportService, canonical
from .service import paginate


def report_chunk(drawings, snapshot_id, offset, length):
    if not re.fullmatch(r"ep_[0-9a-f]{64}", snapshot_id):
        raise ValueError("Invalid snapshot identity")
    if type(offset) is not int or offset < 0 or type(length) is not int or not 1 <= length <= 16000:
        raise ValueError("Use nonnegative byte offset and length 1..16000")
    exports = ExportService(drawings)
    path = exports.folder / "snapshots" / (snapshot_id + ".json")
    if not path.resolve().is_relative_to(drawings.config.state.resolve()):
        raise ValueError("Report resource escaped selected app state")
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Use paginated report tools for snapshots larger than 16 MiB")
    body = exports.load(snapshot_id)
    raw = canonical(body).encode("utf-8")
    if len(raw) > 16 * 1024 * 1024 or offset > len(raw):
        raise ValueError("Snapshot grew beyond budget or offset exceeds its bytes")
    part = raw[offset : offset + length]
    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "total_bytes": len(raw),
        "offset": offset,
        "next_offset": offset + len(part) if offset + len(part) < len(raw) else None,
        "encoding": "base64",
        "data": base64.b64encode(part).decode("ascii"),
        "source_freshness": paginate(exports.freshness(body), 0, 10),
        "scope": "Selected app's private state and root permissions; no independent chat-owner claim",
        "native_engine_validated": False,
    }


def register_report_resources(server, drawings):
    @server.resource("eplan://reports/{snapshot_id}/{offset}/{length}", mime_type="application/json")
    def read_report(snapshot_id: str, offset: int, length: int) -> str:
        """Read verified report bytes in bounded chunks; discover no private report inventory."""
        value = json.dumps(report_chunk(drawings, snapshot_id, offset, length), ensure_ascii=False)
        if len(value.encode()) > 200_000:
            raise ValueError("Resource metadata exceeds response budget; use report tools")
        return value
