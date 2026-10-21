"""Thin MCP adapters for the EPLAN export service."""

from .exports import FIELDS, KINDS, ExportService


def register_exports(tool, drawings):
    service = ExportService(drawings)

    @tool(control=True)
    def eplan_capabilities() -> dict:
        """Read export schema, supported analyses and native EPLAN boundaries before importing reports."""
        return {
            "report_kinds": sorted(KINDS),
            "canonical_fields": sorted(FIELDS),
            "formats": [
                "csv",
                "tsv",
                "txt",
                "json",
                "flat XML with explicit row_tag",
                "flat EPJ with explicit row_tag",
            ],
            "native_project_access": False,
            "native_editing": False,
            "native_highlighting": False,
            "inventory_only": ["zw1", "zw9", "ema", "ems"],
            "independent_readers": [
                "nested XML",
                "Access base tables (Windows ACE)",
                "ELK/ELL link text",
                "ordinary ZIP members",
                "raw binary ranges",
                "ASCII-compatible binary text",
                "checksum-valid zlib streams",
            ],
            "binary_semantic_project_decoder": False,
            "mapping": "field_map maps canonical names to exact exported column/property names; no numeric property IDs guessed",
            "limits": {"report_bytes": 16777216, "snapshot_rows": 100000, "report_count": 32},
            "workflow": "Import explicitly declared exports; query snapshot_id; inspect freshness on every response.",
        }

    @tool(read=False)
    def eplan_import_reports(root_id: str, reports: list[dict]) -> dict:
        """Create immutable EPLAN evidence from declared CSV/TSV/JSON/flat XML exports.

        Each declaration: {relative_path, kind, field_map?, row_tag?, delimiter?}.
        Kinds: devices, connections, plc_io, terminals, cables, parts, network, pages.
        field_map maps canonical field to exact source column. XML requires exact row_tag.
        Writes only private state; source reports remain unchanged. Native ELK/ZW1 cannot be imported here.
        """
        return service.import_reports(root_id, reports)

    @tool()
    def eplan_get_export_snapshot(snapshot_id: str) -> dict:
        """Read snapshot counts, declared mappings, limitations and current source hashes/freshness."""
        return service.get(snapshot_id)

    @tool()
    def eplan_query_export(
        snapshot_id: str, kind: str, query: str | None = None, offset: int = 0, limit: int = 50
    ) -> dict:
        """Query exported devices, connections, PLC I/O, terminals, cables, parts, network or pages.

        Includes raw properties, explicit canonical mapping, source SHA-256 and row ordinal.
        Does not combine records by unqualified device tags. Unknown properties remain raw.
        """
        return service.query(snapshot_id, kind, query, offset, limit)

    @tool()
    def eplan_check_exports(snapshot_id: str, offset: int = 0, limit: int = 50) -> dict:
        """Review potential duplicate device tags, PLC/network addresses and missing connection endpoints.
        Duplicate functions can be legitimate; findings require review and are not native check-run results.
        """
        return service.checks(snapshot_id, offset, limit)

    @tool()
    def eplan_trace_export_connection(
        snapshot_id: str, tag: str, terminal: str | None = None, max_depth: int = 10, max_edges: int = 100
    ) -> dict:
        """Trace exact source/target tag+terminal assertions from exported connection rows.
        Requires full structured tags. No implicit device-internal bridges or physical continuity claims.
        """
        return service.trace(snapshot_id, tag, terminal, max_depth, max_edges)

    @tool()
    def eplan_compare_export_snapshots(
        before_snapshot_id: str, after_snapshot_id: str, offset: int = 0, limit: int = 50
    ) -> dict:
        """Compare mapped export records, preserving duplicate multiplicity and both source manifests."""
        return service.compare(before_snapshot_id, after_snapshot_id, offset, limit)

    @tool(read=False)
    def eplan_export_snapshot(snapshot_id: str) -> dict:
        """Write and readback-verify JSON evidence in private state; returns artifact path and SHA-256."""
        return service.export(snapshot_id)
