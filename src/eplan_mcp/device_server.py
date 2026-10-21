"""Device facts, explicit supply traces and drawing evidence through the shared service."""

from .device_information import DeviceInformation, collect_evidence


def register_devices(tool, drawings):
    service = DeviceInformation(drawings)

    @tool()
    def eplan_get_device_profile(
        snapshot_id: str,
        tag: str,
        installation: str | None = None,
        location: str | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> dict:
        """Read exact-tag device descriptions, IPs, PLC I/O facts and power/air supply summaries.
        Uses declared exports or explicitly reviewed drawing rows. Retains quote/hash references,
        conflicting facts and known scope ambiguity. Reviewer labels are not authenticated.
        Facts retain sources; first ten per field are returned with full counts. Use query_export for more.
        """
        return service.profile(snapshot_id, tag, installation, location, offset, limit)

    @tool()
    def eplan_trace_device_supply(
        snapshot_id: str,
        tag: str,
        medium: str = "electrical",
        terminal: str | None = None,
        installation: str | None = None,
        location: str | None = None,
        max_depth: int = 20,
        max_paths: int = 20,
    ) -> dict:
        """Trace upstream power or air feeds from explicit terminal relationships to reported supplies.
        medium is electrical or pneumatic. connections/bridges require explicit flow_direction;
        supply_links declare source-to-target flow by kind. No bridges, ratings or live valve states inferred.
        reported_references retains feed labels/sheet references; these never create terminal graph edges.
        """
        return service.supply(
            snapshot_id, tag, medium, terminal, installation, location, max_depth, max_paths
        )

    @tool()
    def eplan_collect_device_evidence(
        root_id: str,
        drawing_paths: list[str],
        device_query: str | None = None,
        category: str | None = None,
        radius: float = 80,
        offset: int = 0,
        limit: int = 50,
    ) -> dict:
        """Collect source-bound device text, IP literals, power/air labels and I/O-address candidates.
        Index drawings first. category: device, ip, power, air, io or omitted for all. When device_query
        is supplied, include exact literal matches and PDF text within radius points on that same page.
        Proximity is candidate evidence only: it never establishes device ownership or feed connectivity.
        """
        return collect_evidence(
            drawings, root_id, drawing_paths, device_query, category, radius, offset, limit
        )
