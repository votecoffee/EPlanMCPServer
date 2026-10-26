"""Bounded lightweight per-chat metadata; scarce analysis runs only on demand."""

from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import inspect
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import jsonschema
from mcp.server.caching import CacheHint
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.server.mcpserver.tools import Tool
from mcp.types import CallToolResult, ToolAnnotations
from universal_tools.extensions import ExtensionServer

from . import EXTRACTION_VERSION, __package_version__, __version__
from .coordination import Coordinator, RequestScheduler
from .feature_profiles import profiles
from .guidance import WORKFLOW
from .guide_publication import GuidancePublication
from .json_state import atomic_json
from .native_threads import status as native_thread_status
from .owned_processes import bind_evidence, contain_frontdoor, snapshot
from .owned_processes import run as owned_run
from .transactions import Transactions
from .worker_launch import worker_command

CONTROL = {
    "eplan_get_workflow",
    "eplan_status",
    "eplan_concurrency_status",
    "eplan_get_transaction",
    "eplan_capabilities",
}


class Frontdoor:
    def __init__(self, config, config_path):
        self.config, self.path = config, Path(config_path).absolute()
        self.coordinator = Coordinator(
            config.state, config.lock_timeout_seconds, config.max_worker_processes, config.max_oda_processes
        )
        # One costly call per owning tree; parallel chats share the separate
        # global analysis pool. This keeps nested parser/converter trees bounded.
        self.scheduler = RequestScheduler(1, config.max_queued_requests)
        # Keep guidance tied to the serving generation while sharing operational
        # admission, journals and parser caches with old live generations.
        self.guidance = GuidancePublication(
            config.state / "frontdoor-guidance" / __package_version__, self.coordinator
        )
        self.transactions = Transactions(config.state, self.coordinator)
        self.catalog = json.loads(Path(__file__).with_name("tool_catalog.json").read_bytes())
        self.tools = {t["name"]: t for t in self.catalog["tools"]}
        (config.state / "analysis-calls").mkdir(exist_ok=True)

    def status(self):
        engines = {n: importlib.metadata.version(d) for n, d in [("ezdxf", "ezdxf"), ("PyMuPDF", "pymupdf")]}
        extractor = Path(__file__).with_name("extract.py")
        with extractor.open("rb") as stream:
            extractor_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        signature = hashlib.sha256(
            json.dumps(
                {
                    "schema": EXTRACTION_VERSION,
                    "ezdxf": engines["ezdxf"],
                    "pymupdf": engines["PyMuPDF"],
                    "oda": self.config.oda_sha256 if self.config.oda_executable else None,
                    "extractor": extractor_sha,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        return {
            "name": "EPLAN MCP Server",
            "version": __version__,
            "package_version": __package_version__,
            "profile": self.config.profile,
            "roots": {k: str(v) for k, v in self.config.roots.items()},
            "state_dir": str(self.config.state),
            "oda_available": bool(self.config.oda_executable),
            "supported_extensions": sorted(self.config.supported_extensions),
            "native_thread_limits": native_thread_status(),
            "engines": engines,
            "oda_executable": str(self.config.oda_executable) if self.config.oda_executable else None,
            "extraction_signature": signature,
            "concurrency": {
                "max_concurrent_requests_per_process": 1,
                "configured_request_upper_bound": self.config.max_concurrent_requests,
                "max_queued_requests_per_process": self.config.max_queued_requests,
                "max_worker_processes_per_state": self.config.max_worker_processes,
                "max_oda_processes_per_state": self.config.max_oda_processes,
                "lock_timeout_seconds": self.config.lock_timeout_seconds,
            },
            "limits": {
                "max_file_bytes": self.config.max_file_bytes,
                "worker_timeout_seconds": self.config.worker_timeout,
                "response_bytes": 200_000,
            },
            "engine_observation": "Installed metadata only; native libraries are not loaded into the metadata process",
            "resident_analysis_modules": {
                name: name in sys.modules for name in ("numpy", "ezdxf", "pymupdf")
            },
            "admission": self.admission(),
            "native_eplan": {"connected": False},
            "limitations": ["No native EPLAN editing, Access/ACE, controller, shared-host or HTTP route"],
        }

    def admission(self):
        return {
            "metadata_frontdoors_per_state": 12,
            "analysis_operations_per_state": min(4, self.config.max_concurrent_requests),
            "parser_workers_per_state": self.config.max_worker_processes,
            "oda_workers_per_state": self.config.max_oda_processes,
            "owner_job_max_processes": 12,
            "owner_job_max_private_commit_bytes": 768 * 1024 * 1024,
            "scope": "Metadata leases never reserve analysis/parser/ODA slots. Legacy live endpoints remain untouched.",
        }

    def execute(self, kind, name, arguments):
        with self.coordinator.analysis(self.config.max_concurrent_requests):
            with tempfile.TemporaryDirectory(dir=self.config.state / "analysis-calls") as folder:
                folder = Path(folder)
                request = folder / "request.json"
                output = folder / "result.json"
                value = {"kind": kind, "name": name, "arguments": arguments}
                if len(json.dumps(value).encode()) > 200_000:
                    raise ValueError("Request exceeds 200000 byte budget")
                atomic_json(request, value)
                try:
                    result = owned_run(
                        worker_command("_invoke", str(self.path), str(request), str(output)),
                        timeout=self.config.worker_timeout * 5 + 30,
                        stdin=subprocess.DEVNULL,
                    )
                except subprocess.TimeoutExpired as error:
                    raise ValueError(
                        "Analysis call timed out; inspect durable request_id before retrying"
                    ) from error
                if result.returncode or not output.exists():
                    raise ValueError(
                        "Analysis process did not complete; inspect durable request_id before retrying"
                    )
                if output.stat().st_size > 200_000:
                    raise ValueError("Analysis response exceeds budget")
                body = json.loads(output.read_bytes())
                if "error" in body:
                    raise ValueError(body["error"])
                if kind == "resource":
                    return body["result"]
                wire = CallToolResult.model_validate(body["wire_result"])
                if wire.is_error:
                    raise ValueError(" ".join(getattr(c, "text", "") for c in wire.content))
                if wire.structured_content is None:
                    raise ValueError("Analysis returned no structured result")
                return wire.structured_content

    def metadata(self, name, args):
        if name == "eplan_get_workflow":
            return self.guidance.read(**args)
        if name == "eplan_status":
            return self.status()
        if name == "eplan_concurrency_status":
            return {
                **self.scheduler.status(),
                "admission": self.admission(),
                "resource_ownership": snapshot(),
                "operation_observations": {
                    "scope": "This frontdoor; backend stage status is returned on completion; no durable job survival"
                },
                "native_eplan": "not connected",
            }
        if name == "eplan_get_transaction":
            return self.transactions.get(**args)
        value = copy.deepcopy(self.catalog["capabilities"])
        value["selected_profile"] = self.config.profile
        value["feature_profiles"] = profiles(self.config.profile, bool(self.config.oda_executable))
        value["disabled_routes"] = [
            r for r in value["disabled_routes"] if r != "unconfigured vendor converter"
        ]
        if not self.config.oda_executable:
            value["disabled_routes"].append("unconfigured vendor converter")
        value["frontdoor_admission"] = self.admission()
        value["progress_delivery"] = (
            "Ephemeral analysis returns final real stage observations; live stage streaming is not provided"
        )
        return value

    async def call(self, name, args):
        row = self.tools[name]
        try:
            jsonschema.validate(args, row["inputSchema"])
        except jsonschema.ValidationError as error:
            raise ToolError("Invalid arguments: " + error.message) from error
        try:
            return (
                await self.scheduler.run(self.metadata, name, args, control=True)
                if name in CONTROL
                else await self.scheduler.run(self.execute, "tool", name, args)
            )
        except ValueError as error:
            raise ToolError(str(error)) from error


def create_frontdoor(config, config_path):
    front = Frontdoor(config, config_path)
    tools = []

    def bound_call(name):
        async def invoke(**kwargs) -> dict[str, Any]:
            return await front.call(name, kwargs)

        return invoke

    for row in front.catalog["tools"]:
        invoke = bound_call(row["name"])
        invoke.__name__ = row["name"]
        parameters = [
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Any,
                default=spec.get("default", inspect.Parameter.empty)
                if name not in row["inputSchema"].get("required", [])
                else inspect.Parameter.empty,
            )
            for name, spec in row["inputSchema"].get("properties", {}).items()
        ]
        invoke.__signature__ = inspect.Signature(parameters, return_annotation=dict[str, Any])
        invoke.__annotations__ = {**{p.name: Any for p in parameters}, "return": dict[str, Any]}
        tool = Tool.from_function(
            invoke,
            name=row["name"],
            description=row.get("description", ""),
            annotations=ToolAnnotations.model_validate(row.get("annotations") or {}),
            structured_output=True,
        )
        tool.parameters = row["inputSchema"]
        tools.append(tool)

    server = ExtensionServer(
        "EPLAN MCP Server",
        version=__version__,
        instructions=WORKFLOW,
        tools=tools,
        cache_hints={"tools/list": CacheHint(ttl_ms=1000, scope="private")},
        extensions=[front.guidance.catalog],
        resource_providers=[front.guidance.catalog],
    )

    @server.resource("eplan://reports/{snapshot_id}/{offset}/{length}", mime_type="application/json")
    async def report(snapshot_id: str, offset: int, length: int) -> str:
        try:
            return json.dumps(
                await front.scheduler.run(
                    front.execute,
                    "resource",
                    "report",
                    {"snapshot_id": snapshot_id, "offset": offset, "length": length},
                )
            )
        except ValueError as error:
            raise ResourceError(str(error)) from error

    server.eplan_scheduler = front.scheduler
    server.eplan_frontdoor = front
    return server


def serve(config, config_path):
    from .management import Reporting

    bind_evidence(config.state)
    coordinator = Coordinator(config.state)
    with coordinator.frontdoor():
        contain_frontdoor()
        server = create_frontdoor(config, config_path)
        with Reporting(
            config.state,
            server.eplan_scheduler.status,
            role="Lightweight metadata frontdoor; analysis acquired lazily",
        ):
            server.run(transport="stdio")
