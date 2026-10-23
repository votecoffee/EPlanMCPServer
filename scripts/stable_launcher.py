"""Installed stable stdlib-only entry. No cache/source discovery, install or fallback."""

from __future__ import annotations

import hashlib
import json
import os
import re
import site
import sys
from pathlib import Path


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ordinary(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.exists() and (item.is_symlink() or getattr(item.stat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("Linked/reparse installation paths are refused")
    return path


def read_json(path, maximum=4_000_000):
    path = ordinary(path)
    if path.stat().st_size > maximum:
        raise ValueError("Installation record exceeds budget")
    return json.loads(path.read_bytes())


def verify(root, selection=None):
    root = ordinary(root)
    pointer = root / "launcher/current.json"
    proposed = selection is not None
    selection = read_json(pointer, 65536) if selection is None else selection
    if selection.get("schema_version") != 1 or not re.fullmatch(
        "[a-f0-9]{64}", selection.get("snapshot", "")
    ):
        raise ValueError("Invalid runtime selection")
    snapshot = ordinary(root / "runtimes" / selection["snapshot"])
    manifest = snapshot / "inventory.json"
    if digest(manifest) != selection["manifest_sha256"]:
        raise ValueError("Runtime inventory identity changed")
    inventory = read_json(manifest)
    if digest(root / "Start-Mcp.py") != selection["entry_sha256"]:
        raise ValueError("Stable entry identity changed")
    if digest(selection["interpreter"]) != selection["interpreter_sha256"]:
        raise ValueError("Reviewed interpreter identity changed")
    engine = ordinary(Path(selection["interpreter"]).parent)
    if (
        not engine.is_relative_to(root / "engines")
        or digest(engine / "inventory.json") != selection["engine_sha256"]
    ):
        raise ValueError("Reviewed Python engine identity changed")
    engine_inventory = read_json(engine / "inventory.json")
    for name, value in engine_inventory.items():
        path = Path(name)
        if path.is_absolute() or path.drive or ".." in path.parts or ":" in name:
            raise ValueError("Invalid Python engine path")
        if digest(ordinary(engine / path)) != value:
            raise ValueError("Reviewed Python engine bytes changed")
    if {p.relative_to(engine).as_posix() for p in engine.rglob("*") if p.is_file()} != set(
        engine_inventory
    ) | {"inventory.json"}:
        raise ValueError("Python engine inventory changed")
    entries = inventory["files"]
    if not 1 <= len(entries) <= 15000:
        raise ValueError("Invalid runtime inventory size")
    expected = {"inventory.json"}
    for name, expected_hash in entries.items():
        relative = Path(name)
        if relative.is_absolute() or relative.drive or ".." in relative.parts or ":" in name:
            raise ValueError("Invalid runtime inventory path")
        path = ordinary(snapshot / relative)
        if digest(path) != expected_hash:
            raise ValueError("Reviewed runtime payload changed")
        expected.add(relative.as_posix())
    observed = set()
    for directory, folders, files in os.walk(snapshot):
        for name in folders:
            ordinary(Path(directory, name))
        observed.update(Path(directory, name).relative_to(snapshot).as_posix() for name in files)
    if observed != expected:
        raise ValueError("Runtime inventory contains missing or unexpected files")
    if (
        not proposed
        and pointer.read_bytes()
        != json.dumps(selection, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    ):
        raise ValueError("Selection changed or has noncanonical bytes")
    return selection, inventory, snapshot


def watch_parent():
    """Retain the exact parent generation; a held duplicate wire cannot hide parent death."""
    import threading

    from universal_tools.windows_resources import ProcessDriver

    driver = ProcessDriver()
    parent = driver._open(os.getppid())
    own = driver.capture(os.getpid())
    if not parent.alive() or int(parent.identity["created"]) > int(own["created"]):
        parent.close()
        raise ValueError("Launch parent identity cannot be established")

    def wait():
        try:
            result = driver.kernel.WaitForSingleObject(parent.handle, 0xFFFFFFFF)
            if result == 0:
                os._exit(70)  # OS closes this owner's kill-on-close jobs; journals stay uncertain.
            os._exit(71)
        finally:
            parent.close()

    threading.Thread(target=wait, name="eplan-exact-parent", daemon=True).start()


def main():
    if len(sys.argv) != 1:
        raise ValueError("The stable MCP entry accepts no arguments")
    root = Path(__file__).absolute().parent
    selection, inventory, snapshot = verify(root)
    os.chdir(root)
    sys.dont_write_bytecode = True
    # No user-site/PYTHONPATH or third-party base-interpreter fallback.
    sys.path[:] = [p for p in sys.path if "site-packages" not in p.casefold()]
    site.addsitedir(str(snapshot / "runtime/Lib/site-packages"))
    sys.executable = str(snapshot / "runtime/Scripts/python.exe")
    sys.prefix = sys.exec_prefix = str(snapshot / "runtime")
    for name in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[name] = "1"
    os.environ.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH="",
        PYTHONHOME="",
        PYTHONIOENCODING="utf-8",
        PYTHONUNBUFFERED="1",
        EPLAN_INSTALL_ROOT=str(root),
    )
    if selection.get("registry"):
        os.environ["EPLAN_MANAGEMENT_REGISTRY"] = selection["registry"]
    import importlib.metadata

    for name, version in inventory["dependencies"].items():
        if importlib.metadata.version(name) != version:
            raise ValueError("Reviewed dependency version changed")
    watch_parent()
    from eplan_mcp.__main__ import main as serve

    sys.argv = ["eplan_mcp", "--config", str(snapshot / "config.json"), "serve"]
    return serve()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        print(f"EPLAN stable launch refused: {error}", file=sys.stderr)
        raise SystemExit(1)
