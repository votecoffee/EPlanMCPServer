"""Candidate converter tests use inert files and a stubbed owned runner; no native execution."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from eplan_mcp.config import LOCAL_READERS_PROFILE, Config
from eplan_mcp.extract import convert


def test_explicit_profile_and_executable_identity(tmp_path):
    source = tmp_path / "sources"
    source.mkdir()
    binary = tmp_path / "converter.exe"
    binary.write_bytes(b"harmless identity fixture")
    config = tmp_path / "config.json"
    data = {
        "roots": {"fixture": str(source)},
        "state_dir": str(tmp_path / "state"),
        "profile": LOCAL_READERS_PROFILE,
        "oda_executable": str(binary),
        "oda_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    }
    config.write_text(json.dumps(data))
    loaded = Config.load(config)
    assert ".dwg" in loaded.supported_extensions
    binary.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash changed"):
        loaded.validate_converter()


def test_owned_converter_copy_and_hash_checks(tmp_path, monkeypatch):
    source = tmp_path / "source.dwg"
    source.write_bytes(b"synthetic drawing")
    binary = tmp_path / "converter.exe"
    binary.write_bytes(b"inert executable fixture")
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    calls = []

    def owned(args, **kwargs):
        calls.append((args, kwargs))
        Path(args[2], "source.dxf").write_text("synthetic output")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("eplan_mcp.extract.run_owned", owned)
    result, metadata = convert(source, str(binary), profile=LOCAL_READERS_PROFILE, expected_sha256=digest)
    assert result.name == "source.dxf" and metadata["audit"] is False
    assert calls[0][1]["timeout"] == 60 and calls[0][0][-3:] == ["0", "0", "source.dwg"]
    assert source.read_bytes() == b"synthetic drawing"


def test_hash_mismatch_refused_before_launch(tmp_path, monkeypatch):
    binary = tmp_path / "converter.exe"
    binary.write_bytes(b"inert")
    monkeypatch.setattr("eplan_mcp.extract.run_owned", lambda *a, **kw: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="hash changed"):
        convert(tmp_path / "source.dwg", str(binary), profile=LOCAL_READERS_PROFILE, expected_sha256="0" * 64)


def test_source_mutation_discarded(tmp_path, monkeypatch):
    source = tmp_path / "source.dwg"
    source.write_bytes(b"synthetic")
    binary = tmp_path / "converter.exe"
    binary.write_bytes(b"inert")

    def owned(args, **kwargs):
        source.write_bytes(b"mutated")
        Path(args[2], "source.dxf").write_text("output")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("eplan_mcp.extract.run_owned", owned)
    with pytest.raises(ValueError, match="changed during conversion"):
        convert(
            source,
            str(binary),
            profile=LOCAL_READERS_PROFILE,
            expected_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        )
