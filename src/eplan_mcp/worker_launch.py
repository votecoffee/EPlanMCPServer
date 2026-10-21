"""Keep nested workers on the selected immutable app backend publication."""

import sys
from pathlib import Path

_deployment: tuple[Path, str] | None = None


def bind_deployment(root: Path, digest: str):
    global _deployment
    _deployment = (root, digest)


def worker_command(operation: str, *arguments: str) -> list[str]:
    if operation not in {"_extract", "_render", "_tables", "_local"}:
        raise ValueError("Unknown app worker operation")
    if _deployment is not None:
        root, digest = _deployment
        return [sys.executable, "-I", str(root / "worker.py"), digest, operation, *arguments]
    return [sys.executable, "-m", "eplan_mcp", operation, *arguments]
