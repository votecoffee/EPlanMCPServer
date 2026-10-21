"""Immutable backend entrypoint; verify app deployment bytes before importing handlers."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path


def verify_deployment(root: Path, expected: str) -> dict:
    raw = (root / "deployment.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Backend deployment manifest changed; publish a new revision")
    manifest = json.loads(raw)
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported EPLAN deployment manifest")
    actual = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.name != "deployment.json"
    }
    if actual != set(manifest["files"]):
        raise ValueError("Backend deployment file inventory changed")
    for name, digest in manifest["files"].items():
        relative = Path(name)
        target = root / relative
        if relative.is_absolute() or ".." in relative.parts or ":" in name:
            raise ValueError("Invalid backend deployment path")
        if target.is_symlink() or not target.resolve(strict=True).is_relative_to(root.resolve()):
            raise ValueError("Backend deployment escaped its directory")
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Backend deployment bytes changed; publish a new revision")
    if platform.python_version() != manifest["python_version"]:
        raise ValueError("Backend Python runtime changed; reassess and republish")
    for name, version in manifest["dependencies"].items():
        if importlib.metadata.version(name) != version:
            raise ValueError("Backend dependency version changed; reassess and republish")
    config = Path(manifest["config"])
    if hashlib.sha256(config.read_bytes()).hexdigest() != manifest["config_sha256"]:
        raise ValueError("App configuration changed; publish a new backend revision")
    return manifest


def main():
    if len(sys.argv) < 2:
        raise ValueError("Use the app-owned backend publication")
    root = Path(__file__).resolve().parent
    manifest = verify_deployment(root, sys.argv[1])
    # The snapshot's package takes precedence over an editable development installation.
    sys.path.insert(0, str(root))
    from eplan_mcp.__main__ import main as backend
    from eplan_mcp.worker_launch import bind_deployment

    bind_deployment(root, sys.argv[1])
    if len(sys.argv) > 2:
        if sys.argv[2] not in {"_extract", "_render", "_tables", "_local"}:
            raise ValueError("Unknown immutable backend worker operation")
        sys.argv = [sys.argv[0], *sys.argv[2:]]
    else:
        sys.argv = [sys.argv[0], "--config", manifest["config"], "serve", "--workflow"]
    backend()


if __name__ == "__main__":
    main()
