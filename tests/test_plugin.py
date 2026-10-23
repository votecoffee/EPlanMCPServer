import json
import shutil
from pathlib import Path

import pytest

from scripts.install_plugin import FILES, prepare


def test_plugin_binding_uses_stable_installation_and_keeps_skills(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1]
    repo = tmp_path / "source & files"
    for name in FILES:
        target = repo / "plugins/eplan" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "plugins/eplan" / name, target)
    drawings = tmp_path / "drawings"
    drawings.mkdir()
    config = repo / ".local/config.json"
    config.parent.mkdir()
    config.write_bytes(json.dumps({"roots": {"test": str(drawings)}}).encode())
    python = repo / ".venv/Scripts/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"inert fixture")
    with pytest.raises(ValueError, match="stable installation"):
        prepare(repo)
    stable = tmp_path / "durable app"
    snapshot = stable / "runtimes/fixture"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_bytes(config.read_bytes())
    selected = {"interpreter": str(stable / "engines/reviewed/python.exe")}
    monkeypatch.setattr("scripts.stable_launcher.verify", lambda root: (selected, {}, snapshot))
    result = prepare(repo, stable_root=stable)
    package = Path(result["package"])
    binding = json.loads((package / "mcp.json").read_bytes())["mcpServers"]["eplan"]
    assert binding["command"] == selected["interpreter"]
    assert binding["args"] == ["-I", "-B", str(stable / "Start-Mcp.py")]
    assert binding["cwd"] == str(stable)
    assert (package / "skills/eplan-analysis/SKILL.md").is_file()
    assert json.loads((repo / "plugins/eplan/mcp.json").read_bytes())["mcpServers"] == {}
    assert prepare(repo, stable_root=stable)["package"] == str(package)
    with pytest.raises(ValueError, match="not selected"):
        prepare(repo, stable_root=stable, frontend="framework")
