"""Pure refusal tests; no worker, converter, COM provider, server or controller startup."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from eplan_mcp.config import PROFILE, SUPPORTED, Config
from eplan_mcp.extract import convert
from eplan_mcp.local_data import LocalDataService, run_worker


def test_config_has_no_vendor_discovery_or_environment_opt_in(tmp_path, monkeypatch):
    root = tmp_path / "sources"
    root.mkdir()
    path = tmp_path / "config.json"
    data = {"roots": {"synthetic": str(root)}, "state_dir": str(tmp_path / "state")}
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("EPLAN_ODA_EXECUTABLE", "must-not-be-read.exe")
    config = Config.load(path)
    assert config.oda_executable is None and SUPPORTED == {".dxf", ".pdf"}
    data["oda_executable"] = "must-not-run.exe"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="disabled"):
        Config.load(path)
    data.pop("oda_executable")
    data["profile"] = "vendor-or-shared"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=PROFILE):
        Config.load(path)


@pytest.mark.parametrize("operation,options", [("access", {}), ("archive", {"member_operation": "access"})])
def test_access_and_archive_access_refused_before_source_or_worker_access(operation, options):
    reader = LocalDataService(SimpleNamespace(config=SimpleNamespace()))
    with pytest.raises(ValueError, match="disabled"):
        reader.read("synthetic", "nonexistent.mdb", operation, **options)


def test_low_level_worker_cannot_reenable_access(tmp_path):
    with pytest.raises(ValueError, match="disabled"):
        run_worker(
            str(tmp_path / "nonexistent.mdb"), str(tmp_path / "no-result.json"), '{"operation":"access"}'
        )
    assert not (tmp_path / "no-result.json").exists()


def test_converter_cannot_be_reenabled_by_an_executable_argument():
    with pytest.raises(ValueError, match="disabled"):
        convert(Path("nonexistent.dwg"), "must-not-run.exe")


def test_http_startup_refused_before_config_or_transport_load(monkeypatch):
    from eplan_mcp.__main__ import _main

    monkeypatch.setattr("sys.argv", ["eplan-mcp", "serve", "--transport", "streamable-http"])
    with pytest.raises(ValueError, match="Only direct stdio"):
        _main()
