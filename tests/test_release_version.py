"""Pure release identity and CLI-parser checks; no service or plugin startup."""

import json
import re
import shutil
import threading
from pathlib import Path

import pytest
from packaging.version import Version

from eplan_mcp import __package_version__, __version__, management
from eplan_mcp.release_version import canonical_identity, canonical_timestamp, equivalent_versions
from scripts.stamp_release import stamp, verify


@pytest.mark.parametrize(
    "display,canonical",
    [
        ("26.0102.030405", "26.102.30405"),
        ("06.0102.000001", "6.102.1"),
        ("00.0229.235959", "0.229.235959"),
        ("26.1231.000000", "26.1231.0"),
    ],
)
def test_padded_display_has_canonical_pep440_and_strict_semver_identity(display, canonical):
    assert canonical_timestamp(display) == canonical
    assert str(Version(display)) == canonical
    assert re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", canonical)
    assert equivalent_versions(display, canonical)


@pytest.mark.parametrize(
    "invalid",
    [
        "26.0102.0304",
        "26.0002.030405",
        "26.0230.030405",
        "26.0229.030405",
        "26.0102.240000",
        "26.0102.036000",
        "26.0102.030460",
    ],
)
def test_invalid_timestamp_cannot_be_stamped(invalid):
    with pytest.raises(ValueError):
        canonical_timestamp(invalid)


def test_fixed_source_plugin_and_build_metadata_match():
    repo = Path(__file__).resolve().parents[1]
    record = verify(repo)
    assert record["display_version"] == __version__
    assert record["package_version"] == __package_version__ == canonical_timestamp(__version__)
    assert canonical_identity("0.3.0") == "0.3.0"  # Legacy receipts remain distinguishable/readable.


@pytest.mark.parametrize("display", ["26.0102.030405", "06.0102.000001"])
def test_stamper_keeps_display_padding_and_leaves_dependency_pins_unchanged(tmp_path, display):
    source = Path(__file__).resolve().parents[1]
    for relative in (
        "src/eplan_mcp/release_version.py",
        "pyproject.toml",
        "README.md",
        "plugins/eplan/plugin.json",
        "plugins/eplan/.codex-plugin/plugin.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / relative).read_bytes())
    result = stamp(tmp_path, display)
    assert result["display_version"] == display
    assert result["package_version"] == canonical_timestamp(display)
    project = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert "universal-codex-tools==0.20.0" in project and "mcp==2.3.0" in project
    assert __version__ != display  # Isolated fixture stamping never changes the active release.


def test_cli_version_exits_before_config_or_server_loading(monkeypatch, capsys):
    from eplan_mcp.__main__ import _main

    monkeypatch.setattr("sys.argv", ["eplan-mcp", "--version"])
    with pytest.raises(SystemExit) as result:
        _main()
    assert result.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_prepared_plugin_package_uses_fixed_canonical_identity(tmp_path):
    from scripts.install_plugin import prepare

    source = Path(__file__).resolve().parents[1]
    shutil.copytree(source / "plugins", tmp_path / "plugins")
    python = tmp_path / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"not executable; metadata-only test")
    root = tmp_path / "synthetic-sources"
    root.mkdir()
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"roots": {"synthetic": str(root)}, "state_dir": str(tmp_path / "state")}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="stable installation"):
        prepare(tmp_path, config)
    # Source templates contain skills but no unsafe implicit HTTP/checkout route.
    for name in ("mcp.json", ".mcp.json"):
        assert json.loads((tmp_path / "plugins/eplan" / name).read_bytes())["mcpServers"] == {}


def test_management_compares_numeric_app_plugin_components(tmp_path, monkeypatch):
    reporting = object.__new__(management.Reporting)
    reporting.state = tmp_path
    reporting.guard = threading.Lock()
    reporting.versions = {}
    reporting.plugin_running = None
    (tmp_path / "management-installation.json").write_text(
        json.dumps({"plugin_id": management.PLUGIN_ID, "plugin_version": "26.0102.030405"}), encoding="utf-8"
    )
    monkeypatch.setattr(management, "__package_version__", "26.102.30405")
    monkeypatch.setattr(
        management.importlib.metadata,
        "version",
        lambda name: "26.0102.030405" if name == "eplan-mcp-server" else "2.3.0",
    )
    reporting.refresh_versions()
    for key in ("app", "plugin"):
        component = reporting.versions[key]
        assert component.installed == component.running == "26.102.30405"
    assert reporting.versions["sdk"].installed == "2.3.0"
