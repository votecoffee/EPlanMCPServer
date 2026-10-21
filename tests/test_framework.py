import json
from pathlib import Path

import pytest

from eplan_mcp import framework_host
from eplan_mcp.framework_entry import verify_deployment
from eplan_mcp.integration import OFFLINE_WRITES
from eplan_mcp.server import create_server


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


@pytest.mark.anyio
async def test_framework_export_handlers_and_immutable_publication(exports, tmp_path):
    exports_service, root, declarations = exports
    drawings = exports_service.drawings
    config = root.parent / "config.json"
    state = tmp_path / "framework-host"
    published = framework_host.prepare(config, state)
    publication = Path(published["publication"])
    entry = Path(published["deployment"])
    verify_deployment(entry, entry.name)
    async with framework_host.create_host(state, publication, config) as host:
        client = host.client()
        native = await create_server(drawings, workflow=True).list_tools()
        assert len(native) == 47
        for tool in native:
            description = payload(
                await client.invoke("describe_tool", {"tool_id": "drawing-engine/" + tool.name})
            )
            assert description["definition"] == tool.model_dump(mode="json", by_alias=True, exclude_none=True)
            assert description["callable"] == (tool.annotations.read_only_hint or tool.name in OFFLINE_WRITES)

        async def call(name, arguments, request_id=None):
            desc = payload(await client.invoke("describe_tool", {"tool_id": "drawing-engine/" + name}))
            args = {
                "tool_id": desc["tool_id"],
                "catalog_revision": desc["catalog_revision"],
                "arguments": arguments,
            }
            if request_id:
                args["request_id"] = request_id
            return payload(await client.invoke(desc["invocation"]["channel"], args))

        imported = await call(
            "eplan_import_reports",
            {"root_id": "test", "reports": declarations, "request_id": "inner-report-import"},
            "outer-report-import",
        )
        identifier = imported["snapshot_id"]
        records = await call("eplan_query_export", {"snapshot_id": identifier, "kind": "devices"})
        assert records["total"] == 2
        xml = await call(
            "eplan_read_xml",
            {"root_id": "test", "relative_path": "io.xml", "record_tag": "Point", "limit": 1},
        )
        assert xml["items"][0]["value"]["children"][0]["text"] == "A1"
        exported = await call(
            "eplan_export_snapshot",
            {"snapshot_id": identifier, "request_id": "inner-report-export"},
            "outer-report-export",
        )
        assert Path(exported["path"]).is_file()
        assert (await call("eplan_get_transaction", {"request_id": "inner-report-export"}))[
            "state"
        ] == "succeeded"
    (entry / "eplan_mcp/exports.py").write_text("# tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="bytes changed"):
        verify_deployment(entry, entry.name)


def test_native_highlighting_is_rejected(drawing_service, tmp_path):
    _, root = drawing_service
    with pytest.raises(ValueError, match="not supported"):
        framework_host.prepare(root.parent / "config.json", tmp_path / "host", highlighting=True)
