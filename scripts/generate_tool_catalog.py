"""Render the native-library-free frontend schema from the actual pinned backend."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from eplan_mcp.config import Config
from eplan_mcp.server import create_server
from eplan_mcp.service import DrawingService


async def main(check=False):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        (root / "source").mkdir()
        server = create_server(DrawingService(Config({"synthetic": root / "source"}, root / "state")))
        tools = await server.list_tools()
        capabilities = await server.call_tool("eplan_capabilities", {})
        value = {
            "schema_version": 1,
            "tools": [t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools],
            "capabilities": capabilities.structured_content,
        }
        target = Path(__file__).resolve().parents[1] / "src/eplan_mcp/tool_catalog.json"
        payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
        if check:
            if target.read_bytes() != payload:
                raise ValueError("Frontend catalog differs from the actual pinned backend; regenerate it")
        else:
            target.write_bytes(payload)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify without changing the catalog")
    asyncio.run(main(parser.parse_args().check))
