import asyncio
import base64
import hashlib
import json
import threading
import time

import pytest
from mcp import Client

from eplan_mcp.report_resources import report_chunk
from eplan_mcp.server import create_server


@pytest.mark.anyio
async def test_import_progress_and_bounded_report_resource_share_snapshot_store(exports):
    exports_service, root, declarations = exports
    server = create_server(exports_service.drawings)
    events = []

    async def progress(done, total, message):
        events.append((done, total, message))

    async with Client(server, mode="legacy", cache=None) as client:
        result = await client.call_tool(
            "eplan_import_reports",
            {
                "root_id": "test",
                "reports": declarations,
                "request_id": "progress-import-0001",
            },
            progress_callback=progress,
        )
        assert not result.is_error, result.content
        body = result.structured_content
        assert body["operation_status"]["state"] == "completed"
        assert [e[0] for e in events] == list(range(1, len(declarations) + 2))
        assert all(e[1] == len(declarations) + 1 for e in events)
        identifier = body["snapshot_id"]
        offset, chunks = 0, []
        while offset is not None:
            resource = await client.read_resource(f"eplan://reports/{identifier}/{offset}/512")
            value = json.loads(resource.contents[0].text)
            assert value["snapshot_id"] == identifier and not value["native_engine_validated"]
            chunks.append(base64.b64decode(value["data"]))
            offset = value["next_offset"]
        raw = b"".join(chunks)
        assert hashlib.sha256(raw).hexdigest() == identifier.removeprefix("ep_")
        assert json.loads(raw) == exports_service.load(identifier)
        (root / "devices.csv").write_text("DT,Text\nchanged,changed\n")
        changed = report_chunk(exports_service.drawings, identifier, 0, 512)
        assert any(s["state"] == "changed" for s in changed["source_freshness"]["items"])
        assert changed["sha256"] == value["sha256"]
        for uri in (f"eplan://reports/{identifier}/0/16001", "eplan://reports/not-an-id/0/512"):
            with pytest.raises(Exception):
                await client.read_resource(uri)


@pytest.mark.anyio
async def test_cancelled_index_never_claims_inflight_worker_rollback(drawing_service, monkeypatch):
    drawings, _ = drawing_service
    started, release = threading.Event(), threading.Event()
    effects = []

    def work(root_id, relative_path):
        effects.append(relative_path)
        started.set()
        assert release.wait(5)
        time.sleep(0.05)  # Cancellation delivery is asynchronous; an additional unit may be in flight.
        return {"text": [], "source": {"sha256": "0" * 64}}

    monkeypatch.setattr(drawings, "_index_file", work)
    server = create_server(drawings)
    async with Client(server, mode="2026-07-28", cache=None) as client:
        task = asyncio.create_task(
            client.call_tool(
                "eplan_index_project",
                {
                    "root_id": "test",
                    "limit": 3,
                    "request_id": "cancel-index-0001",
                },
            )
        )
        try:
            for _ in range(200):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert started.is_set()
            task.cancel()
            await asyncio.sleep(0.05)
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        for _ in range(200):
            status = await client.call_tool("eplan_concurrency_status", {})
            observations = status.structured_content["operation_observations"]["items"]
            if observations and observations[0]["state"] not in {
                "running",
                "queued",
                "cancellation_requested",
            }:
                break
            await asyncio.sleep(0.01)
        assert 1 <= len(effects) < 3
        assert observations[0]["state"] in {"stopped_at_checkpoint", "uncertain"}
        assert not observations[0]["worker_preempted"]
        receipt = await client.call_tool("eplan_get_transaction", {"request_id": "cancel-index-0001"})
        assert receipt.structured_content["state"] == "unknown"


@pytest.mark.anyio
async def test_modern_private_discovery_cache_saves_round_trips_without_cross_client_sharing(drawing_service):
    drawings, _ = drawing_service
    server = create_server(drawings)
    calls = []

    async def counted(ctx, call_next):
        if ctx.method == "tools/list":
            calls.append(1)
        return await call_next(ctx)

    server.middleware.append(counted)
    async with Client(server, mode="2026-07-28") as first:
        await first.list_tools()
        count = len(calls)
        await first.list_tools()
        assert len(calls) == count
        async with Client(server, mode="2026-07-28") as second:
            await second.list_tools()
            assert len(calls) == count + 1
        await first.list_tools(cache_mode="refresh")
        assert len(calls) == count + 2


@pytest.mark.anyio
async def test_cancelled_import_preserves_sources_and_does_not_publish_partial_snapshot(exports, monkeypatch):
    import eplan_mcp.exports as module
    from eplan_mcp.service import sha256

    exports_service, root, declarations = exports
    before = {p.name: sha256(p) for p in root.iterdir() if p.is_file()}
    entered, release = threading.Event(), threading.Event()
    parse = module.parse_report

    def blocked_parse(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return parse(*args, **kwargs)

    monkeypatch.setattr(module, "parse_report", blocked_parse)
    async with Client(create_server(exports_service.drawings), mode="2026-07-28", cache=None) as client:
        task = asyncio.create_task(
            client.call_tool(
                "eplan_import_reports",
                {
                    "root_id": "test",
                    "reports": declarations,
                    "request_id": "cancel-import-0001",
                },
            )
        )
        try:
            for _ in range(200):
                if entered.is_set():
                    break
                await asyncio.sleep(0.01)
            assert entered.is_set()
            task.cancel()
            await asyncio.sleep(0.05)
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not list((exports_service.folder / "snapshots").glob("*.json"))
        assert {p.name: sha256(p) for p in root.iterdir() if p.is_file()} == before
        receipt = await client.call_tool("eplan_get_transaction", {"request_id": "cancel-import-0001"})
        assert receipt.structured_content["state"] == "unknown"
