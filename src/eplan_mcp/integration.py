"""Standalone Codex plugin installation policy; never dispatches drawing operations."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .owned_processes import run as run_owned

PLUGIN_ID = "eplan@eplan-local"
OFFLINE_WRITES = (
    "eplan_import_reports",
    "eplan_export_snapshot",
    "eplan_index_project",
    "eplan_render_preview",
    "eplan_build_electrical_project",
    "eplan_export_electrical_project",
)
HIGHLIGHT = "eplan_highlight_source_object"


def installed_plugins(codex: str) -> dict:
    result = run_owned(
        [codex, "plugin", "list", "--json"],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    inventory = json.loads(result.stdout)
    if not isinstance(inventory, dict) or not isinstance(inventory.get("installed"), list):
        raise ValueError("Codex did not return a supported plugin inventory")
    plugins = {}
    for item in inventory["installed"]:
        if not isinstance(item, dict) or not isinstance(item.get("pluginId"), str):
            raise ValueError("Codex returned a malformed plugin entry")
        plugins[item["pluginId"]] = item
    return plugins


def select_route(mode: str, plugins: dict, previous: dict | None) -> dict:
    if mode == "none":
        return {"route": "none", "action": "preserve", "reason": "Codex integration explicitly skipped"}
    if mode == "standalone":
        return {"route": "standalone", "action": "install", "reason": "Explicit standalone selection"}
    if mode != "auto":
        raise ValueError("Choose auto, standalone or none")
    if previous is not None:
        if previous.get("route") not in {"none", "standalone"}:
            raise ValueError(
                "Saved integration is no longer supported; run --install-plugin to select standalone"
            )
        if previous["route"] == "none":
            return {"route": "none", "action": "preserve", "reason": "Preserved skipped plugin installation"}
    plugin = plugins.get(PLUGIN_ID, {})
    if plugin.get("installed") is True and plugin.get("enabled") is not True:
        return {"route": "standalone", "action": "preserve", "reason": "Preserved disabled app plugin"}
    return {"route": "standalone", "action": "install", "reason": "Install or refresh the standalone plugin"}


def integration_plan(repo: Path, mode: str) -> dict:
    record = repo / ".local/codex-integration.json"
    previous = json.loads(record.read_text(encoding="utf-8")) if record.exists() else None
    if mode in {"none", "standalone"}:
        plan = select_route(mode, {}, previous)
        if mode == "standalone" and not shutil.which("codex"):
            raise ValueError("Codex CLI was not found")
        return plan
    # Validate saved preferences before optional CLI discovery.
    plan = select_route(mode, {}, previous)
    if plan["route"] == "none":
        return plan
    codex = shutil.which("codex")
    if not codex:
        return {"route": None, "action": "defer", "reason": "Codex CLI unavailable; application is usable"}
    try:
        plugins = installed_plugins(codex)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"route": None, "action": "defer", "reason": "Plugin inventory unavailable; choices preserved"}
    return select_route(mode, plugins, previous)
