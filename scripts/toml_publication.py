"""Explicit UTF-8 TOML copy publication; never edits the user's live Codex configuration."""

from __future__ import annotations

import copy
import hashlib
import os
import re
import tempfile
import tomllib
from pathlib import Path

LIVE_CONFIG = Path.home() / ".codex" / "config.toml"


def encode_toml(text: str, *, newline: str | None = None) -> bytes:
    if newline is None:
        newline = "\r\n" if os.name == "nt" else "\n"
    if newline not in {"\n", "\r\n"}:
        raise ValueError("Select LF or CRLF explicitly")
    if re.search(r"\r(?!\n)", text):
        raise ValueError("Lone CR or CRCRLF input is refused; review the original bytes")
    logical = text.replace("\r\n", "\n")
    parsed = tomllib.loads(logical)
    data = logical.replace("\n", newline).encode("utf-8")
    if tomllib.loads(data.decode("utf-8")) != parsed:
        raise ValueError("TOML newline conversion changed settings")
    return data


def _without(settings, paths):
    result = copy.deepcopy(settings)
    for path in paths:
        if not path or any(not isinstance(part, str) or not part for part in path):
            raise ValueError("Changed setting paths must be nonempty string tuples")
        current = result
        parents = []
        for part in path[:-1]:
            if not isinstance(current, dict) or part not in current:
                break
            parents.append((current, part))
            current = current[part]
        else:
            if isinstance(current, dict):
                current.pop(path[-1], None)
                for parent, part in reversed(parents):
                    if parent[part] == {}:
                        parent.pop(part)
    return result


def publish_copy(
    path: Path, text: str, *, expected_sha256: str | None, allowed_changes=(), newline: str | None = None
) -> dict:
    path = Path(path)
    if path.resolve() == LIVE_CONFIG.resolve():
        raise ValueError("Live Codex configuration is protected; publish a review copy instead")
    data = encode_toml(text, newline=newline)
    prior = path.read_bytes() if path.exists() else None
    actual = hashlib.sha256(prior).hexdigest() if prior is not None else None
    if actual != expected_sha256:
        raise ValueError("TOML copy changed since review")
    if prior is not None:
        old = tomllib.loads(prior.decode("utf-8"))
        new = tomllib.loads(data.decode("utf-8"))
        if _without(old, allowed_changes) != _without(new, allowed_changes):
            raise ValueError("Unrelated settings changed")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".toml.tmp")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        current = path.read_bytes() if path.exists() else None
        if current != prior:
            raise ValueError("TOML copy changed during publication")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "newline": "CRLF" if b"\r\n" in data else "LF",
        "live_config_written": False,
    }
