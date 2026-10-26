"""One ephemeral app-owned analysis call; no wire or management endpoint here."""

import asyncio
import json
import traceback
from pathlib import Path

from .config import Config
from .json_state import atomic_json
from .owned_processes import bind_evidence


def run_worker(config, request, output):
    request, output = Path(request), Path(output)
    if request.stat().st_size > 200_000:
        raise ValueError("Analysis request exceeds 200000 bytes")
    cfg = Config.load(config)
    bind_evidence(cfg.state)
    if not request.resolve().is_relative_to(cfg.state / "analysis-calls") or output.parent != request.parent:
        raise ValueError("Analysis exchange must stay in selected private state")
    value = json.loads(request.read_bytes())

    async def invoke():
        from mcp.server.mcpserver.exceptions import ToolError

        from .server import create_server
        from .service import DrawingService

        service = DrawingService(cfg)
        server = create_server(service)
        try:
            if value.get("kind") == "resource":
                from .report_resources import report_chunk

                result = report_chunk(service, **value["arguments"])
                return {"result": result}
            result = await server.call_tool(value["name"], value["arguments"])
            return {"wire_result": result.model_dump(mode="json", by_alias=True)}
        except (ToolError, ValueError) as error:
            return {"error": str(error)}
        except Exception:
            traceback.print_exc()
            return {
                "error": "Unexpected analysis failure; inspect private diagnostics and any durable request_id"
            }

    result = asyncio.run(invoke())
    if len(json.dumps(result).encode()) > 200_000:
        result = {"error": "Response exceeds budget; narrow the query or pagination"}
    atomic_json(output, result)
