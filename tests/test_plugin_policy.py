"""Pure routing policy; no CLI, plugin inventory, process or server invocation."""

import pytest

from eplan_mcp.integration import PLUGIN_ID, integration_plan, select_route


@pytest.mark.parametrize(
    "inventory",
    [
        {},
        {"unrelated@other": {"installed": True, "enabled": True}},
        {"unrelated@other": {"installed": True, "enabled": False}},
    ],
)
def test_app_plugin_selection_is_independent_of_other_plugins(inventory):
    assert select_route("auto", inventory, None)["route"] == "standalone"
    assert select_route("auto", inventory, None)["action"] == "install"
    disabled = {**inventory, PLUGIN_ID: {"installed": True, "enabled": False}}
    assert select_route("auto", disabled, None)["action"] == "preserve"
    assert select_route("none", inventory, None)["route"] == "none"
    assert select_route("auto", inventory, {"route": "none"})["route"] == "none"


@pytest.mark.parametrize("saved", ["broker", "universal"])
def test_obsolete_saved_route_does_not_silently_migrate(saved):
    with pytest.raises(ValueError, match="no longer supported"):
        select_route("auto", {}, {"route": saved})


def test_saved_skip_does_not_probe_cli_or_any_plugin(tmp_path, monkeypatch):
    folder = tmp_path / ".local"
    folder.mkdir()
    (folder / "codex-integration.json").write_text('{"route":"none"}', encoding="utf-8")

    def forbidden(*args):
        pytest.fail("A saved skip must not invoke CLI or inspect plugin inventory")

    monkeypatch.setattr("eplan_mcp.integration.shutil.which", forbidden)
    monkeypatch.setattr("eplan_mcp.integration.installed_plugins", forbidden)
    assert integration_plan(tmp_path, "auto")["route"] == "none"
