import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import stable_install as install
from scripts import stable_launcher as launch


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "installed space caf\u00e9"
    root.mkdir()
    (root / "Start-Mcp.py").write_bytes(Path(launch.__file__).read_bytes())
    engine = root / "engines" / ("e" * 64)
    engine.mkdir(parents=True)
    (engine / "python.exe").write_bytes(b"not executable fixture")
    (engine / "inventory.json").write_bytes(
        install.canonical({"python.exe": launch.digest(engine / "python.exe")})
    )
    runtime = root / "runtimes" / ("a" * 64)
    runtime.mkdir(parents=True)
    (runtime / "payload.py").write_bytes(b"# immutable fixture\n")
    manifest = {"files": {"payload.py": launch.digest(runtime / "payload.py")}, "dependencies": {}}
    (runtime / "inventory.json").write_bytes(install.canonical(manifest))
    selection = {
        "schema_version": 1,
        "snapshot": runtime.name,
        "manifest_sha256": launch.digest(runtime / "inventory.json"),
        "entry_sha256": launch.digest(root / "Start-Mcp.py"),
        "interpreter": str(engine / "python.exe"),
        "interpreter_sha256": launch.digest(engine / "python.exe"),
        "engine_sha256": launch.digest(engine / "inventory.json"),
        "app_version": "26.1023.120000",
    }
    install.select(root, selection, None)
    return root, runtime, selection


def test_selection_independent_of_cwd_cache_and_unicode(installation, tmp_path, monkeypatch):
    root, _, selected = installation
    cache = tmp_path / "disposable plugin cache"
    cache.mkdir()
    cache.rmdir()
    monkeypatch.chdir(tmp_path)
    assert launch.verify(root)[0] == selected


@pytest.mark.parametrize("target", ["payload.py", "inventory.json"])
def test_payload_tamper_refused(installation, target):
    root, runtime, _ = installation
    (runtime / target).write_bytes(b"tampered")
    with pytest.raises((ValueError, KeyError)):
        launch.verify(root)


def test_missing_extra_and_linked_selection_refused(installation):
    root, runtime, _ = installation
    pointer = root / "launcher/current.json"
    prior = pointer.read_bytes()
    pointer.unlink()
    with pytest.raises(OSError):
        launch.verify(root)
    pointer.write_bytes(prior)
    (runtime / "unreviewed.py").write_bytes(b"extra")
    with pytest.raises(ValueError, match="unexpected"):
        launch.verify(root)


def test_cas_and_interrupted_selection_preserve_prior(installation, monkeypatch):
    root, _, selected = installation
    pointer = root / "launcher/current.json"
    prior = pointer.read_bytes()
    changed = {**selected, "app_version": "26.1023.120001"}
    with pytest.raises(ValueError, match="Concurrent"):
        install.select(root, changed, "0" * 64)
    assert pointer.read_bytes() == prior

    def fail(*args):
        raise OSError("disposable interruption")

    monkeypatch.setattr(install.os, "replace", fail)
    with pytest.raises(OSError):
        install.select(root, changed, hashlib.sha256(prior).hexdigest())
    assert pointer.read_bytes() == prior
    assert launch.verify(root)[0] == selected


def test_publication_lock_serializes_cooperating_writers(installation):
    root, _, selected = installation
    with install.publication_lock(root):
        with pytest.raises(OSError):
            install.select(root, selected, launch.digest(root / "launcher/current.json"))


def test_proposed_bad_payload_cannot_replace_prior_selection(installation):
    root, runtime, selected = installation
    prior = (root / "launcher/current.json").read_bytes()
    (runtime / "payload.py").write_bytes(b"drift")
    with pytest.raises(ValueError):
        install.select(root, {**selected, "app_version": "new"}, hashlib.sha256(prior).hexdigest())
    assert (root / "launcher/current.json").read_bytes() == prior


@pytest.mark.parametrize("target", ["pointer", "payload"])
def test_actual_startup_refuses_before_execution_in_unicode_path(installation, target):
    root, runtime, _ = installation
    if target == "pointer":
        (root / "launcher/current.json").write_bytes(b"{}")
    else:
        (runtime / "payload.py").write_bytes(b'raise RuntimeError("MUST_NOT_EXECUTE")')
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(root / "Start-Mcp.py")],
        cwd=root.parent,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 1 and result.stdout == b""
    assert b"EPLAN stable launch refused" in result.stderr and b"MUST_NOT_EXECUTE" not in result.stderr


def test_linked_selection_is_refused(installation, monkeypatch):
    root, _, _ = installation
    pointer = root / "launcher/current.json"
    from types import SimpleNamespace

    original = Path.lstat

    def linked(path, *args, **kwargs):
        return (
            SimpleNamespace(st_mode=0, st_file_attributes=0x400)
            if path == pointer
            else original(path, *args, **kwargs)
        )

    monkeypatch.setattr(Path, "lstat", linked)
    with pytest.raises(ValueError, match="Linked/reparse"):
        launch.verify(root)
