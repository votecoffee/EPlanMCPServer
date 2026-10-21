import sys

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.anyio
async def test_real_stdio_drawing_and_export_workflows(exports):
    service, root, declarations = exports
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "eplan_mcp", "--config", str(root.parent / "config.json"), "serve"],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=60.0) as client:
            initialized = await client.initialize()
            assert initialized.server_info.name == "EPLAN MCP Server"
            tools = (await client.list_tools()).tools
            assert len(tools) == 49
            assert not any("highlight" in t.name for t in tools)
            inspected = await client.call_tool(
                "eplan_inspect", {"root_id": "test", "relative_path": "sample.pdf"}
            )
            assert not inspected.is_error and inspected.structured_content["text_records"] > 0
            args = {"root_id": "test", "reports": declarations, "request_id": "export-import-1"}
            first = await client.call_tool("eplan_import_reports", args)
            assert not first.is_error, first.content
            identifier = first.structured_content["snapshot_id"]
            second = await client.call_tool("eplan_import_reports", args)
            assert second.structured_content["transaction"]["replayed"]
            for name, arguments in [
                ("eplan_query_export", {"snapshot_id": identifier, "kind": "devices", "limit": 1}),
                ("eplan_get_export_snapshot", {"snapshot_id": identifier}),
                ("eplan_check_exports", {"snapshot_id": identifier}),
                (
                    "eplan_trace_export_connection",
                    {"snapshot_id": identifier, "tag": "=AP+ST1-X1", "terminal": "1"},
                ),
                (
                    "eplan_compare_export_snapshots",
                    {"before_snapshot_id": identifier, "after_snapshot_id": identifier},
                ),
                ("eplan_export_snapshot", {"snapshot_id": identifier, "request_id": "evidence-export-1"}),
            ]:
                result = await client.call_tool(name, arguments)
                assert not result.is_error and result.structured_content is not None, result.content
            rejected = await client.call_tool(
                "eplan_query_export", {"snapshot_id": "../secret", "kind": "devices"}
            )
            assert rejected.is_error
