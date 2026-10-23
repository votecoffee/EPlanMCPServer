import pytest
from mcp import Client

from eplan_mcp.server import create_server


@pytest.mark.anyio
async def test_emitted_bounds_defaults_and_expected_error(drawing_service, monkeypatch):
    drawings, _ = drawing_service
    async with Client(create_server(drawings), mode="legacy", cache=None) as client:
        tools = await client.list_tools()
        by_name = {tool.name: tool for tool in tools.tools}
        props = by_name["eplan_list_files"].input_schema["properties"]
        assert props["limit"]["minimum"] == 1 and props["limit"]["maximum"] == 200
        assert props["limit"]["default"] == 100 and props["offset"]["minimum"] == 0
        batch = by_name["eplan_index_project"].input_schema["properties"]["limit"]
        assert batch["maximum"] == 5 and batch["default"] == 2
        bad = await client.call_tool("eplan_list_files", {"root_id": "missing"})
        assert bad.is_error and "Unknown root_id" in str(bad.content)
        invalid = await client.call_tool("eplan_list_files", {"root_id": "test", "limit": 201})
        assert invalid.is_error

        def crash(*args, **kwargs):
            raise RuntimeError("PRIVATE_UNEXPECTED_SENTINEL")

        monkeypatch.setattr(drawings, "inventory", crash)
        result = await client.call_tool("eplan_list_files", {"root_id": "test"})
        assert result.is_error and "PRIVATE_UNEXPECTED_SENTINEL" not in str(result.content)
