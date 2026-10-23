from __future__ import annotations

import inspect
import json
from functools import wraps
from typing import Annotated, Any

from mcp.server.caching import CacheHint
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

try:
    from mcp.server import MCPServer

    SDK2 = True
except ImportError:
    # Keep existing editable 0.3 installations usable until their explicit runtime upgrade.
    from mcp.server.fastmcp import FastMCP as MCPServer

    SDK2 = False

from . import __version__
from .coordination import RequestScheduler
from .guidance import WORKFLOW
from .guide_publication import GuidancePublication
from .operation_progress import Operations, current
from .service import DrawingService
from .transactions import Transactions


def create_server(service: DrawingService, port: int = 8816, *, workflow: bool = False) -> MCPServer:
    scheduler = RequestScheduler(service.config.max_concurrent_requests, service.config.max_queued_requests)
    transactions = Transactions(service.config.state, service.coordinator)
    operations = Operations()
    guidance = GuidancePublication(service.config.state, service.coordinator)
    from universal_tools.extensions import ExtensionServer

    mcp = ExtensionServer(
        "EPLAN MCP Server",
        instructions=WORKFLOW,
        extensions=[guidance.catalog],
        resource_providers=[guidance.catalog],
        cache_hints={"tools/list": CacheHint(ttl_ms=1000, scope="private")},
        **({"version": __version__} if SDK2 else {"host": "127.0.0.1", "port": port}),
    )
    mcp.eplan_scheduler = scheduler
    from .report_resources import register_report_resources

    register_report_resources(mcp, service)

    def tool(*, read=True, control=False):
        def decorate(fn):
            fn.__annotations__["return"] = dict[str, Any]
            original_signature = inspect.signature(fn)

            @wraps(fn)
            async def wrapped(*args, **kwargs):
                context = kwargs.pop("mcp_context", None)
                request_id = kwargs.pop("request_id", None) if not read else None
                bound = original_signature.bind(*args, **kwargs)
                bound.apply_defaults()

                hook = (
                    operations.start(fn.__name__, context)
                    if fn.__name__ in {"eplan_index_project", "eplan_import_reports"}
                    else None
                )

                def execute():
                    if hook:
                        hook.started = True
                        hook.update(state="running")
                        hook.check()
                    return fn(*args, **kwargs)

                token = current.set(hook)
                try:
                    if read:
                        result = await scheduler.run(execute, control=control)
                    else:
                        result = await scheduler.run(
                            transactions.execute, request_id, fn.__name__, dict(bound.arguments), execute
                        )
                    if hook:
                        hook.update(state="completed")
                        result = {**result, "operation_status": hook.status()}
                except BaseException as error:
                    if hook:
                        hook.update(
                            state="failed"
                            if isinstance(error, Exception)
                            else "stopped_at_checkpoint"
                            if hook.cancelled
                            else "cancelled_before_dispatch"
                            if not hook.started
                            else "uncertain"
                        )
                    if isinstance(error, ValueError):
                        raise ToolError(str(error)) from error
                    raise
                finally:
                    current.reset(token)
                if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 200_000:
                    raise ValueError("Response exceeds budget; use smaller limit or narrower filters")
                return result

            if not read:
                wrapped.__signature__ = original_signature.replace(
                    parameters=[
                        *original_signature.parameters.values(),
                        inspect.Parameter(
                            "request_id", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=str | None
                        ),
                    ]
                )
                wrapped.__annotations__ = {**fn.__annotations__, "request_id": str | None}
                wrapped.__doc__ = (
                    (fn.__doc__ or "")
                    + "\nOptional request_id provides durable idempotency; inspect eplan_get_transaction after a lost response."
                )

            signature = getattr(wrapped, "__signature__", original_signature)
            # Expose actual shared pagination bounds; specialized batch operations
            # retain their own narrower validators below.
            annotations = dict(wrapped.__annotations__)
            parameters = []
            for parameter in signature.parameters.values():
                if parameter.name == "offset":
                    parameter = parameter.replace(annotation=Annotated[int, Field(ge=0, strict=True)])
                elif parameter.name == "limit":
                    maximum = 5 if fn.__name__ == "eplan_index_project" else 200
                    parameter = parameter.replace(
                        annotation=Annotated[int, Field(ge=1, le=maximum, strict=True)]
                    )
                annotations[parameter.name] = parameter.annotation
                parameters.append(parameter)
            wrapped.__annotations__ = annotations
            wrapped.__signature__ = signature.replace(
                parameters=[
                    *parameters,
                    inspect.Parameter(
                        "mcp_context", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=Context
                    ),
                ]
            )
            wrapped.__annotations__ = {**wrapped.__annotations__, "mcp_context": Context}

            return mcp.tool(
                structured_output=True,
                annotations=ToolAnnotations.model_validate(
                    {
                        "readOnlyHint": read,
                        "destructiveHint": False,
                        "idempotentHint": read,
                        "openWorldHint": False,
                    }
                ),
            )(wrapped)

        return decorate

    @tool(control=True)
    def eplan_get_workflow(
        expected_revision: str | None = None,
        reference_id: str | None = None,
        expected_sha256: str | None = None,
    ) -> dict:
        """Read current EPLAN guidance and its reference catalog, or a revision/hash-pinned reference.
        Call without arguments first. Guide content is not write approval or a native EPLAN claim.
        Rediscover after stale pins; preserve the selected endpoint and engineering receipt IDs.
        """
        return guidance.read(expected_revision, reference_id, expected_sha256)

    @tool(control=True)
    def eplan_status() -> dict:
        """List configured source roots, installed backends, supported formats and extraction limits."""
        return service.status()

    @tool(control=True)
    def eplan_concurrency_status() -> dict:
        """Inspect per-process request admission, queue and worker limits; control calls remain responsive under load."""
        from .owned_processes import snapshot

        return {
            **scheduler.status(),
            "resource_ownership": snapshot(),
            "operation_observations": operations.snapshot(),
            "shared_worker_process_limit": service.config.max_worker_processes,
            "shared_oda_process_limit": service.config.max_oda_processes,
            "native_eplan": "not connected",
        }

    @tool(control=True)
    def eplan_get_transaction(request_id: str, include_result: bool = False) -> dict:
        """Read a durable write receipt/result. An abandoned owner is reported unknown; no operation is retried."""
        return transactions.get(request_id, include_result)

    @tool()
    def eplan_list_files(
        root_id: str, supported_only: bool = True, offset: int = 0, limit: int = 100
    ) -> dict:
        """Inventory a configured drawing root recursively. Unsupported CAD formats can be listed too."""
        return service.inventory(root_id, supported_only, offset, limit)

    @tool()
    def eplan_inspect(root_id: str, relative_path: str) -> dict:
        """Extract source SHA-256, metadata, units, entity counts, layouts, PDF page count and limitations."""
        return service.inspect(root_id, relative_path)

    @tool()
    def eplan_get_entities(
        root_id: str,
        relative_path: str,
        layout: str | None = None,
        layer: str | None = None,
        entity_type: str | None = None,
        handle: str | None = None,
        block: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Read CAD entities and geometry properties by layer/layout/type/handle. Block coordinates are local.

        INSERT entities include transforms and attached attributes. Use layout '@block' and block name for
        definitions. Polyline vertices are limited to 256 per record; eplan_entity_vertices retrieves slices.
        """
        return service.records(
            root_id,
            relative_path,
            "entities",
            offset,
            limit,
            layout=layout,
            layer=layer,
            entity_type=entity_type,
            handle=handle,
            block=block,
        )

    @tool()
    def eplan_get_text(
        root_id: str,
        relative_path: str,
        query: str | None = None,
        layout: str | None = None,
        layer: str | None = None,
        page: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> dict:
        """Read/search literal CAD text, block attributes or positioned PDF text. PDF pages are one-based.

        Every row has a record_index plus CAD handle/location or PDF page/bbox. Long text is explicitly
        truncated at 8000 characters; eplan_read_text_record retrieves full text in slices.
        """
        return service.records(
            root_id, relative_path, "text", offset, limit, query=query, layout=layout, layer=layer, page=page
        )

    @tool()
    def eplan_read_text_record(
        root_id: str, relative_path: str, record_index: int, start: int = 0, length: int = 8000
    ) -> dict:
        """Read a slice of one text record, using its zero-based record_index. Maximum length is 16000."""
        return service.text_slice(root_id, relative_path, record_index, start, length)

    @tool()
    def eplan_entity_vertices(
        root_id: str, relative_path: str, handle: str, offset: int = 0, limit: int = 100
    ) -> dict:
        """Read LWPOLYLINE vertex slices [x,y,start_width,end_width,bulge] using a CAD entity handle."""
        doc = service.load(root_id, relative_path)
        row = next((row for row in doc["entities"] if row["handle"] == handle), None)
        if row is None or "vertices" not in row:
            raise ValueError("Handle is not an extracted LWPOLYLINE")
        from .service import paginate

        return {
            "source": doc["source"],
            "handle": handle,
            "closed": row["closed"],
            **paginate(row["vertices"], offset, limit),
        }

    @tool()
    def eplan_get_layers(root_id: str, relative_path: str, offset: int = 0, limit: int = 100) -> dict:
        """Read CAD layer names, colors, linetypes and off/frozen/locked flags."""
        return service.records(root_id, relative_path, "layers", offset, limit)

    @tool()
    def eplan_get_blocks(root_id: str, relative_path: str, offset: int = 0, limit: int = 100) -> dict:
        """Read block definitions, base points and xref paths. Read INSERT entities for attributes/placements."""
        return service.records(root_id, relative_path, "blocks", offset, limit)

    @tool()
    def eplan_get_dimensions(
        root_id: str, relative_path: str, layout: str | None = None, offset: int = 0, limit: int = 100
    ) -> dict:
        """Read dimension entities, raw measurement, type, text override and definition points.

        Values are not formatted dimension labels; dimension style rounding/scaling is not applied.
        """
        return service.records(
            root_id, relative_path, "entities", offset, limit, entity_type="DIMENSION", layout=layout
        )

    @tool()
    def eplan_get_references(root_id: str, relative_path: str, offset: int = 0, limit: int = 100) -> dict:
        """List declared xrefs, image and PDF/DWF/DGN underlay paths; never open or load references."""
        return service.records(root_id, relative_path, "references", offset, limit)

    @tool()
    def eplan_get_pdf_pages(root_id: str, relative_path: str, offset: int = 0, limit: int = 100) -> dict:
        """Read PDF page sizes, rotation, text counts, image counts and image-only OCR candidates."""
        return service.records(root_id, relative_path, "pages", offset, limit)

    @tool()
    def eplan_get_pdf_tables(
        root_id: str, relative_path: str, page: int, offset: int = 0, limit: int = 20
    ) -> dict:
        """Detect and extract PDF table cells on one one-based page; verify against eplan_render_preview."""
        return service.pdf_tables(root_id, relative_path, page, offset, limit)

    @tool(read=False)
    def eplan_index_project(root_id: str, offset: int = 0, limit: int = 2) -> dict:
        """Index 1..5 files into app-owned search state. Continue next_offset until null; inspect failures.

        This writes only the server's cache/index and preserves all source files.
        """
        return service.index(root_id, offset, limit)

    @tool()
    def eplan_search_project(root_id: str, query: str, offset: int = 0, limit: int = 50) -> dict:
        """Search indexed drawing text/attributes literally across one root with exact provenance.

        Stale or deleted files are excluded. Coverage reports missing/stale sources; index first.
        """
        return service.search(root_id, query, offset, limit)

    @tool()
    def eplan_compare_drawings(
        root_id: str,
        relative_path: str,
        other_root_id: str,
        other_relative_path: str,
        offset: int = 0,
        limit: int = 100,
    ) -> dict:
        """Compare text multiplicities and layer/block names across two files; structural content diff only."""
        return service.compare(root_id, relative_path, other_root_id, other_relative_path, offset, limit)

    @tool(read=False)
    def eplan_render_preview(
        root_id: str, relative_path: str, page: int = 1, layout: str = "Model", width: int = 1600
    ) -> dict:
        """Write a PNG preview in app-owned state. PDF page is one-based; CAD uses an exact layout name.

        Width is limited to 3000 pixels. CAD rendering is approximate and may omit unsupported entities.
        """
        return service.render(root_id, relative_path, page, layout, width)

    from .electrical_server import register

    register(tool, service)
    from .export_server import register_exports

    register_exports(tool, service)
    from .local_server import register_local

    register_local(tool, service)
    from .device_server import register_devices

    register_devices(tool, service)
    return mcp
