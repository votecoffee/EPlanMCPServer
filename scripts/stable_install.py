"""Prepare/select retained immutable runtimes; never edits global settings or plugin caches."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

try:
    from .stable_launcher import digest, ordinary, verify
except ImportError:
    from stable_launcher import digest, ordinary, verify


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def wheel_bytes(path, expected):
    if digest(path) != expected:
        raise ValueError("Reviewed application wheel hash changed")
    with zipfile.ZipFile(path) as stream:
        names = stream.namelist()
        if len(names) != len(set(names)) or any(
            Path(n).is_absolute() or ".." in Path(n).parts or ":" in n for n in names
        ):
            raise ValueError("Unsafe wheel inventory")
        (record,) = [n for n in names if n.endswith(".dist-info/RECORD")]
        rows = list(csv.reader(io.StringIO(stream.read(record).decode())))
        if {r[0] for r in rows} != set(names):
            raise ValueError("Incomplete wheel RECORD")
        for name, hash_value, size in rows:
            data = stream.read(name)
            if name != record and (
                hash_value
                != "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
                or int(size) != len(data)
            ):
                raise ValueError("Wheel RECORD identity changed")
        return {name: stream.read(name) for name in names}


def retain_engine(root):
    source = Path(sys._base_executable).resolve(strict=True).parent
    engines = root / "engines"
    engines.mkdir(exist_ok=True)
    stage = engines / (".stage-" + uuid.uuid4().hex)
    stage.mkdir()
    sources = [
        source / n
        for n in (
            "python.exe",
            "pythonw.exe",
            "python3.dll",
            "python313.dll",
            "vcruntime140.dll",
            "vcruntime140_1.dll",
            "LICENSE.txt",
        )
    ]
    if sys.version_info[:2] != (3, 13) or os.name != "nt":
        raise ValueError("Stable deployment currently requires the reviewed Windows Python 3.13 engine")
    for folder in ("Lib", "DLLs"):
        for base, dirs, files in os.walk(source / folder):
            dirs[:] = [n for n in dirs if n not in {"site-packages", "__pycache__", "test", "tests"}]
            for name in dirs:
                ordinary(Path(base, name))
            sources.extend(Path(base, n) for n in files if not n.endswith((".pyc", ".pyo")))
    for path in sources:
        ordinary(path)
        target = stage / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if digest(path) != digest(target):
            raise ValueError("Python engine changed during retention")
    raw = canonical(
        {p.relative_to(stage).as_posix(): digest(p) for p in sorted(stage.rglob("*")) if p.is_file()}
    )
    identity = hashlib.sha256(raw).hexdigest()
    (stage / "inventory.json").write_bytes(raw)
    target = engines / identity
    if target.exists():
        # Same retained engine is reused; the newly copied staging tree is disposable.
        if (target / "inventory.json").read_bytes() != raw:
            raise ValueError("Python engine inventory conflict")
        assert stage.resolve().is_relative_to(engines.resolve())
        shutil.rmtree(stage)
    else:
        os.rename(stage, target)
    return target


def prepare(root, runtime, wheel, wheel_sha256, config, dependencies, *, registry=None):
    root, runtime, config = ordinary(root), ordinary(runtime), ordinary(config)
    if (
        not root.is_absolute()
        or root.is_relative_to(Path(__file__).resolve().parents[1])
        or ".codex/plugins/cache" in root.as_posix().casefold()
    ):
        raise ValueError("Install outside the checkout and disposable plugin caches")
    payload = wheel_bytes(wheel, wheel_sha256)
    dependencies = dict(dependencies)
    (metadata_name,) = [n for n in payload if n.endswith(".dist-info/METADATA")]
    metadata = payload[metadata_name].decode()
    version = next(
        line.removeprefix("Version: ") for line in metadata.splitlines() if line.startswith("Version: ")
    )
    if (
        not metadata_name.startswith("eplan_mcp_server-")
        or dependencies.get("mcp") != "2.3.0"
        or dependencies.get("universal-codex-tools") != "0.20.0"
    ):
        raise ValueError("Use the reviewed EPLAN application and unchanged SDK/framework pins")
    dependencies["eplan-mcp-server"] = version
    from eplan_mcp.config import Config

    Config.load(config)
    root.mkdir(parents=True, exist_ok=True)
    engine = retain_engine(root)
    snapshots = root / "runtimes"
    snapshots.mkdir(exist_ok=True)
    stage = snapshots / (".stage-" + uuid.uuid4().hex)
    stage.mkdir()
    # Preserve the reviewed runtime closure without regenerating or importing bytecode.
    for base, dirs, files in os.walk(runtime):
        dirs[:] = [
            n
            for n in dirs
            if n != "__pycache__" and n != "eplan_mcp" and not n.startswith("eplan_mcp_server-")
        ]
        for name in dirs:
            ordinary(Path(base, name))
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                continue
            source = ordinary(Path(base, name))
            target = stage / "runtime" / source.relative_to(runtime)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if digest(source) != digest(target):
                raise ValueError("Runtime changed during snapshot")
    for name, data in payload.items():
        target = stage / "runtime/Lib/site-packages" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (stage / "config.json").write_bytes(config.read_bytes())
    (stage / "runtime/pyvenv.cfg").write_bytes(
        ("home = " + str(engine) + "\ninclude-system-site-packages = false\nversion = 3.13.9\n").encode()
    )
    inventory = {
        "schema_version": 1,
        "app_version": version,
        "wheel_sha256": wheel_sha256,
        "dependencies": dependencies,
        "files": {
            p.relative_to(stage).as_posix(): digest(p) for p in sorted(stage.rglob("*")) if p.is_file()
        },
    }
    raw = canonical(inventory)
    snapshot_id = hashlib.sha256(raw).hexdigest()
    (stage / "inventory.json").write_bytes(raw)
    snapshot = snapshots / snapshot_id
    if snapshot.exists():
        if (snapshot / "inventory.json").read_bytes() != raw:
            raise ValueError("Immutable snapshot identity conflict")
        for name, value in inventory["files"].items():
            if digest(ordinary(snapshot / name)) != value:
                raise ValueError("Retained immutable snapshot changed")
        assert stage.resolve().is_relative_to(snapshots.resolve())
        shutil.rmtree(stage)
    else:
        os.rename(stage, snapshot)
    entry_source = Path(__file__).with_name("stable_launcher.py")
    entry = root / "Start-Mcp.py"
    if entry.exists() and entry.read_bytes() != entry_source.read_bytes():
        raise ValueError("Stable entry upgrade requires a separately reviewed migration")
    if not entry.exists():
        with entry.open("xb") as stream:
            stream.write(entry_source.read_bytes())
    interpreter = engine / "python.exe"
    return {
        "schema_version": 1,
        "snapshot": snapshot_id,
        "manifest_sha256": snapshot_id,
        "entry_sha256": digest(entry),
        "interpreter": str(interpreter),
        "interpreter_sha256": digest(interpreter),
        "engine_sha256": digest(engine / "inventory.json"),
        "app_version": version,
        "registry": str(Path(registry).absolute()) if registry else None,
    }


@contextmanager
def publication_lock(root):
    path = ordinary(root / "launcher/publication.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def select(root, selection, expected_sha256):
    root = ordinary(root)
    with publication_lock(root):
        pointer = ordinary(root / "launcher/current.json")
        prior = pointer.read_bytes() if pointer.exists() else None
        if (hashlib.sha256(prior).hexdigest() if prior is not None else None) != expected_sha256:
            raise ValueError("Concurrent selection change; prior bytes preserved")
        if prior == canonical(selection):
            return
        # Validate the proposed bytes without exposing a broken selection to connections.
        verify(root, selection)
        if prior is not None:
            backup = root / "launcher" / ("before-" + hashlib.sha256(prior).hexdigest() + ".json")
            if not backup.exists():
                backup.write_bytes(prior)
        fd, temporary = tempfile.mkstemp(dir=pointer.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(canonical(selection))
                stream.flush()
                os.fsync(stream.fileno())
            if (pointer.read_bytes() if pointer.exists() else None) != prior:
                raise ValueError("Selection changed during publication")
            os.replace(temporary, pointer)
        finally:
            Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "runtime", "wheel", "config", "dependencies"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument(
        "--expected-current", help="Exact current selection hash; omit for a new installation"
    )
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args(argv)
    selection = prepare(
        args.root,
        args.runtime,
        args.wheel,
        args.wheel_sha256,
        args.config,
        json.loads(args.dependencies.read_bytes()),
        registry=args.registry,
    )
    select(args.root, selection, args.expected_current)
    verify(args.root)
    print(json.dumps({"root": str(args.root), "selection": selection, "global_settings_changed": False}))


if __name__ == "__main__":
    main()
