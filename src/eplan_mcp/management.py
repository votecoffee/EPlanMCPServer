"""Cached same-user service reporting; process replacement is deliberately unavailable."""

from __future__ import annotations

import importlib.metadata
import json
import os
import threading
from contextlib import contextmanager

from universal_tools.management import ComponentVersion, ManagedService, ManagedStatus, RestartResult

from . import __version__

PLUGIN_ID = "eplan@eplan-local"
SDK_RUNNING = importlib.metadata.version("mcp")
RESTART_REASON = (
    "No surviving EPLAN app supervisor or cross-chat quiescence fence; "
    "pending operations and uncertain receipts cannot be safely drained for process replacement"
)


class Activity:
    def __init__(self):
        self.guard = threading.Lock()
        self.count = 0

    @contextmanager
    def operation(self):
        with self.guard:
            self.count += 1
        try:
            yield
        finally:
            with self.guard:
                self.count -= 1

    def status(self):
        with self.guard:
            return {"active": self.count, "queued": 0, "control_requests": 0}


def track_backend(backend, activity):
    invoke = backend.invoke

    async def tracked(*args, **kwargs):
        with activity.operation():
            return await invoke(*args, **kwargs)

    backend.invoke = tracked


class Reporting:
    def __init__(self, state, activity, *, registry=None):
        self.state, self.activity = state, activity
        self.guard = threading.Lock()
        self.stopped = threading.Event()
        self.versions = {}
        self.plugin_running = None
        self.refresh_versions()
        self.agent = ManagedService(
            "eplan",
            "EPLAN MCP Server",
            self.status,
            restart=self.restart,
            plugin_id=PLUGIN_ID,
            registry=registry or os.environ.get("EPLAN_MANAGEMENT_REGISTRY"),
        )

    def refresh_versions(self):
        # Installer/package metadata only. Never inspect engineering state or attach projects.
        versions = {}
        for key, distribution, running in (
            ("app", "eplan-mcp-server", __version__),
            ("sdk", "mcp", SDK_RUNNING),
        ):
            try:
                installed = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                installed = "unknown"
            versions[key] = ComponentVersion(
                installed=installed, running=running, available=None, update_pending=False
            )
        installed = "unknown"
        try:
            metadata = json.loads((self.state / "management-installation.json").read_bytes())
            if isinstance(metadata, dict) and metadata.get("plugin_id") == PLUGIN_ID:
                version = metadata.get("plugin_version")
                if isinstance(version, str) and 0 < len(version) <= 128:
                    installed = version
        except (OSError, ValueError, KeyError):
            pass
        if not self.versions and installed != "unknown":
            self.plugin_running = installed
        versions["plugin"] = ComponentVersion(
            installed=installed, running=self.plugin_running, available=None, update_pending=False
        )
        with self.guard:
            self.versions = versions

    def status(self):
        activity = self.activity()
        pending = activity["active"] + activity["queued"] + activity["control_requests"]
        with self.guard:
            versions = dict(self.versions)
        return ManagedStatus(
            state="busy" if pending else "running",
            message="Standalone offline analysis; per-instance admitted/queued work only; native EPLAN not connected",
            active_operations=pending,
            versions=versions,
            restart_allowed=False,
            restart_reason=RESTART_REASON,
        )

    @staticmethod
    def restart(_):
        return RestartResult(outcome="blocked", message=RESTART_REASON)

    def _poll(self):
        while not self.stopped.wait(5):
            self.refresh_versions()

    def __enter__(self):
        self.agent.start()
        self.thread = threading.Thread(target=self._poll, name="eplan-version-cache", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopped.set()
        self.thread.join(timeout=6)
        self.agent.close()
