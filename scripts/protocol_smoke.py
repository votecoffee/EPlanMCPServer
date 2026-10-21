"""Real stdio protocol check with optional explicitly declared synthetic reports."""

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def run(config, root, reports=None):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "eplan_mcp", "--config", str(Path(config).resolve(strict=True)), "serve"],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=120.0) as client:
            initialized = await client.initialize()
            tools = (await client.list_tools()).tools
            assert len(tools) == 49
            assert all(tool.output_schema for tool in tools)
            for name in ("eplan_status", "eplan_capabilities"):
                result = await client.call_tool(name, {})
                assert not result.is_error and result.structured_content
            inventory = await client.call_tool("eplan_list_files", {"root_id": root, "supported_only": False})
            assert not inventory.is_error
            snapshot_id = None
            if reports:
                declarations = json.loads(Path(reports).read_text(encoding="utf-8-sig"))
                result = await client.call_tool(
                    "eplan_import_reports",
                    {
                        "root_id": root,
                        "reports": declarations,
                        "request_id": "smoke-" + uuid.uuid4().hex,
                    },
                )
                assert not result.is_error, result.content
                snapshot_id = result.structured_content["snapshot_id"]
                for kind in ("devices", "connections", "plc_io"):
                    result = await client.call_tool(
                        "eplan_query_export", {"snapshot_id": snapshot_id, "kind": kind}
                    )
                    assert not result.is_error
            print(
                json.dumps(
                    {
                        "server": initialized.server_info.name,
                        "tools": len(tools),
                        "snapshot_id": snapshot_id,
                        "passed": True,
                    }
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=".local/config.json")
    parser.add_argument("--root", required=True)
    parser.add_argument("--reports", help="JSON declarations for explicitly selected reports")
    args = parser.parse_args()
    asyncio.run(run(args.config, args.root, args.reports))
