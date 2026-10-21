"""MCP adapters use the same analysis operations as the CLI."""

from .electrical import ElectricalService


def register(tool, drawings):
    service = ElectricalService(drawings)

    @tool(read=False)
    def eplan_build_electrical_project(
        root_id: str,
        drawing_paths: list[str] | None = None,
        electrical_project_path: str | None = None,
        reports: list[dict] | None = None,
        attribute_map: dict | None = None,
        wire_layers: list[str] | None = None,
        tolerance: float = 0.0001,
        include_pdf_candidates: bool = True,
    ) -> dict:
        """Build immutable project evidence after eplan_index_project. WDP supplies membership; explicit reports
        supply native assertions. Reports: [{relative_path, kind, field_map?}]; kinds components, panel,
        plc_connections, from_to, network, drawing_map. DWGIX requires an explicit FILETIME mapping.
        Writes app-owned state. PDF text stays an unassociated candidate. No native engine validation.
        """
        return service.build(
            root_id,
            drawing_paths,
            electrical_project_path,
            reports,
            attribute_map,
            wire_layers,
            tolerance,
            include_pdf_candidates,
        )

    @tool()
    def eplan_get_electrical_project(project_id: str) -> dict:
        """Read project counts, checks and current source freshness. Historical snapshots remain readable."""
        return service.get(project_id)

    @tool()
    def eplan_get_device_inventory(
        project_id: str,
        query: str | None = None,
        offset: int = 0,
        limit: int = 50,
        pdf_candidates_only: bool = False,
    ) -> dict:
        """Read tags, descriptions, manufacturer/catalog, equipment codes and source handles.
        Devices are physical occurrences, including child and panel roles. PDF candidates are separate.
        """
        return service.query(
            project_id, "pdf_candidates" if pdf_candidates_only else "devices", offset, limit, query
        )

    @tool()
    def eplan_get_plc_io(
        project_id: str,
        query: str | None = None,
        trace_connections: bool = False,
        offset: int = 0,
        limit: int = 25,
    ) -> dict:
        """Read controller/rack/slot/channel/address, devices, wires and terminals. Unknown values stay null.
        Optional bounded graph traces carry explicit incomplete/branching status and evidence bases.
        """
        return service.plc_io(project_id, offset, limit, query, trace_connections)

    @tool()
    def eplan_get_connections(
        project_id: str,
        device_id: str | None = None,
        connection_id: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Read graph edges with source objects/report rows, wires/cables and evidence classification."""
        return service.query(
            project_id, "connections", offset, limit, device_id=device_id, code=connection_id
        )

    @tool()
    def eplan_trace_connection(
        project_id: str,
        device_id: str,
        terminal: str | None = None,
        domain: str = "electrical",
        max_depth: int = 40,
        max_paths: int = 20,
    ) -> dict:
        """Trace documented electrical or network paths. Associations never imply continuity.
        Stops at a destination device/terminal; continue from that device to follow another segment.
        Returns unresolved ends, branching and explicit budget truncation, with connection IDs for evidence.
        """
        return service.trace(project_id, device_id, terminal, domain, max_depth, max_paths)

    @tool()
    def eplan_get_equipment_groups(
        project_id: str, query: str | None = None, offset: int = 0, limit: int = 50
    ) -> dict:
        """Read explicit installation/location/panel/station groups and separate WDP membership groups."""
        return service.query(project_id, "equipment_groups", offset, limit, query)

    @tool()
    def eplan_get_network_inventory(
        project_id: str, query: str | None = None, offset: int = 0, limit: int = 50
    ) -> dict:
        """Read documented device addresses, ports/interfaces and unassociated text literals. No network access."""
        return service.query(project_id, "network", offset, limit, query)

    @tool()
    def eplan_check_drawing_consistency(
        project_id: str, code: str | None = None, offset: int = 0, limit: int = 50
    ) -> dict:
        """Review duplicate tags, address conflicts, missing descriptions, references and panel differences.
        Missing scope produces potential conflicts; unavailable comparisons remain explicitly not evaluable.
        """
        return service.query(project_id, "checks", offset, limit, code=code)

    @tool()
    def eplan_compare_electrical_revisions(
        before_project_id: str, after_project_id: str, offset: int = 0, limit: int = 50
    ) -> dict:
        """Compare semantic device/connection records in two historical snapshots with source provenance."""
        return service.compare(before_project_id, after_project_id, offset, limit)

    @tool(read=False)
    def eplan_export_electrical_project(project_id: str) -> dict:
        """Write and readback-verify a complete JSON export in app-owned state; return path/hash."""
        return service.export(project_id)
