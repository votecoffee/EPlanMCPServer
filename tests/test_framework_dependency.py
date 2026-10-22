import base64
import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts.framework_dependency import stage, verify


def fixture_wheel(tmp_path, monkeypatch):
    from scripts import framework_dependency

    wheel = tmp_path / "supplied.whl"
    files = {
        "universal_tools/framework.py": b"# disposable framework fixture\n",
        "universal_codex_tools-0.20.0.dist-info/licenses/LICENSE": b"MIT\n",
        "universal_codex_tools-0.20.0.dist-info/METADATA": (
            b"Metadata-Version: 2.4\nName: universal-codex-tools\nVersion: 0.20.0\nRequires-Dist: mcp==2.3.0\n"
        ),
    }
    record = "universal_codex_tools-0.20.0.dist-info/RECORD"
    rows = [
        f"{name},sha256={base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')},{len(data)}"
        for name, data in files.items()
    ]
    files[record] = ("\n".join([*rows, record + ",,"]) + "\n").encode()
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    monkeypatch.setattr(framework_dependency, "SHA256", hashlib.sha256(wheel.read_bytes()).hexdigest())
    return wheel


def test_modified_framework_wheel_is_rejected_before_installation(tmp_path):
    wheel = tmp_path / "framework.whl"
    wheel.write_bytes(b"modified dependency must never execute")
    with pytest.raises(ValueError, match="SHA-256"):
        verify(wheel)
    with pytest.raises(ValueError, match="SHA-256"):
        stage(tmp_path, str(wheel))
    assert not (tmp_path / ".local/wheels").exists()


def test_setup_requires_explicit_local_framework_artifact(tmp_path):
    with pytest.raises(ValueError, match="--framework-wheel"):
        stage(tmp_path)
    from scripts.launcher import main

    with pytest.raises(ValueError, match="lifecycle profile is unaccepted"):
        main()


def test_explicit_verified_framework_wheel_replaces_older_cache(tmp_path, monkeypatch):
    from scripts.framework_dependency import FILENAME

    wheel = fixture_wheel(tmp_path, monkeypatch)
    target = tmp_path / ".local/wheels" / FILENAME
    target.parent.mkdir(parents=True)
    target.write_bytes(b"earlier framework artifact with the same version")
    directory = stage(tmp_path, str(wheel))
    assert directory == target.parent and target.read_bytes() == wheel.read_bytes()
    assert stage(tmp_path) == directory
    assert list(directory.iterdir()) == [target]


def test_failed_framework_copy_preserves_cached_artifact(tmp_path, monkeypatch):
    from scripts import framework_dependency

    wheel = fixture_wheel(tmp_path, monkeypatch)
    target = tmp_path / ".local/wheels" / framework_dependency.FILENAME
    target.parent.mkdir(parents=True)
    previous = b"preserve the old cache on failed replacement"
    target.write_bytes(previous)
    monkeypatch.setattr(
        framework_dependency.shutil,
        "copyfile",
        lambda source, destination: Path(destination).write_bytes(b"bad"),
    )
    with pytest.raises(ValueError, match="SHA-256"):
        stage(tmp_path, str(wheel))
    assert target.read_bytes() == previous and list(target.parent.iterdir()) == [target]


def test_framework_refuses_an_sdk_downgrade(monkeypatch):
    from eplan_mcp import framework_host

    original = framework_host.importlib.metadata.version
    monkeypatch.setattr(
        framework_host.importlib.metadata,
        "version",
        lambda name: "1.30.0" if name == "mcp" else original(name),
    )
    with pytest.raises(ValueError, match="do not downgrade"):
        framework_host.require_framework()
