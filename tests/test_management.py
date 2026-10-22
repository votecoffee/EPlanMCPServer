import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from universal_tools.management import ManagementClient

from eplan_mcp.management import PLUGIN_ID, RESTART_REASON, Activity, Reporting, track_backend


@pytest.mark.anyio
async def test_framework_activity_is_accounted_and_failure_releases_it():
    activity = Activity()

    class Backend:
        async def invoke(self, name, arguments, *, relay=None):
            assert activity.status()["active"] == 1
            raise ValueError("Synthetic failure")

    backend = Backend()
    track_backend(backend, activity)
    with pytest.raises(ValueError, match="Synthetic failure"):
        await backend.invoke("synthetic", {})
    assert activity.status()["active"] == 0


def test_cached_reporting_versions_busy_denial_and_clean_stop(tmp_path, monkeypatch):
    (tmp_path / "management-installation.json").write_text(
        json.dumps(
            {
                "plugin_id": PLUGIN_ID,
                "plugin_version": "0.3.0",
            }
        )
    )
    activity = Activity()
    registry = tmp_path / "registry"
    with Reporting(tmp_path, activity.status, registry=registry) as report:
        client = ManagementClient(registry)
        row = client.inspect(report.agent.record)
        assert row["plugin_id"] == PLUGIN_ID and row["status"]["state"] == "running"
        assert row["status"]["versions"]["framework"]["running"] == "0.20.0"
        assert row["status"]["versions"]["sdk"]["running"] == "2.3.0"
        assert row["status"]["versions"]["plugin"]["running"] == "0.3.0"
        assert all(
            v["available"] is None and not v["update_pending"] for v in row["status"]["versions"].values()
        )
        assert not row["status"]["restart_allowed"] and RESTART_REASON == row["status"]["restart_reason"]
        with activity.operation():
            busy = client.inspect(report.agent.record)
            assert busy["status"]["state"] == "busy" and busy["status"]["active_operations"] == 1
            stale = client.restart("eplan", report.agent.instance_id, row["revision"], "stale-request-0001")
            assert stale["outcome"] == "blocked"
            current = client.restart(
                "eplan", report.agent.instance_id, busy["revision"], "busy-request-00001"
            )
            assert current["outcome"] == "blocked"
        row = client.inspect(report.agent.record)
        args = ("eplan", report.agent.instance_id, row["revision"], "duplicate-request-0001")
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: client.restart(*args), range(4)))
        assert all(r == receipts[0] and r["outcome"] == "blocked" for r in receipts)
        assert RESTART_REASON == receipts[0]["message"]
        assert report.agent.pending_restarts() == []
        assert "token" not in json.dumps(client.snapshot())
        monkeypatch.setattr(
            "eplan_mcp.management.importlib.metadata.version",
            lambda *_: (_ for _ in ()).throw(AssertionError("I/O")),
        )
        assert report.status().state == "running"  # Callback reads only cached state.
    record = client.registry.records()[0][0]
    assert record.stopped and client.inspect(record)["status"]["state"] == "stopped"


def test_missing_plugin_and_changed_installed_versions_are_explicit(tmp_path):
    report = Reporting(tmp_path, Activity().status, registry=tmp_path / "registry")
    assert report.status().versions["plugin"].installed == "unknown"
    assert report.status().versions["plugin"].running is None
    (tmp_path / "management-installation.json").write_text(
        json.dumps(
            {
                "plugin_id": PLUGIN_ID,
                "plugin_version": "0.4.0",
            }
        )
    )
    report.refresh_versions()
    assert report.status().versions["plugin"].installed == "0.4.0"
    assert report.status().versions["plugin"].running is None
    assert not report.status().restart_allowed
