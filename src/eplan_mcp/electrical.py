"""Shared project analysis, immutable evidence snapshots and structured exports."""

from __future__ import annotations

import collections
import ipaddress
import json
import math
import os
import re
import uuid
from pathlib import Path

from .electrical_graph import (
    ConnectionGraph,
    add_associations,
    add_drawing_geometry,
    add_network_peers,
    add_signal_links,
    annotate_wire_numbers,
    trace_graph,
)
from .electrical_import import ReportImporter
from .electrical_model import (
    SCHEMA_VERSION,
    aliases,
    drawing_metadata,
    issue,
    network_observations,
    normalize_instance,
    pdf_candidates,
    physical_entities,
    plc_channels,
    provenance,
    stable_id,
)
from .electrical_reports import parse_report, parse_wdp
from .service import DrawingService, paginate, sha256

COLLECTIONS = {"devices", "plc_io", "connections", "equipment_groups", "network", "checks", "pdf_candidates"}


def atomic_json(path: Path, value: dict):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False),
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def equipment_key(device):
    return tuple((device.get(k) or "").casefold() for k in ("installation", "location", "tag"))


def consistency(devices, io, network, drawings, diagnostics):
    primary, panels, terminals = (
        collections.defaultdict(list),
        collections.defaultdict(list),
        collections.defaultdict(list),
    )
    for device in devices:
        role = device["role"]
        if role in {"panel", "panel_terminal"}:
            panels[equipment_key(device)].append(device)
        elif role in {"terminal", "panel_terminal"}:
            terminals[equipment_key(device) + (str(device.get("attributes", {}).get("TERM01", "")),)].append(
                device
            )
        elif role != "child" and device.get("tag"):
            primary[equipment_key(device)].append(device)
        if role not in {"child", "terminal", "panel_terminal"} and not device.get("description"):
            diagnostics.append(
                issue(
                    "missing_description",
                    "Device has no documented description",
                    device["sources"],
                    device_id=device["id"],
                )
            )
        if device.get("attribute_conflicts"):
            diagnostics.append(
                issue(
                    "conflicting_attributes",
                    "One occurrence has conflicting repeated attributes",
                    device["sources"],
                    names=device["attribute_conflicts"],
                    device_id=device["id"],
                )
            )
    for key, rows in {**primary, **terminals}.items():
        if len(rows) > 1:
            diagnostics.append(
                issue(
                    "duplicate_tag",
                    "Multiple primary occurrences share the same equipment identity",
                    [s for d in rows for s in d["sources"]],
                    identity=key,
                    device_ids=[d["id"] for d in rows],
                )
            )
    if panels and primary:
        for key in primary.keys() - panels.keys():
            diagnostics.append(
                issue(
                    "schematic_only_device",
                    "No matching panel inventory representation in this scope",
                    primary[key][0]["sources"],
                    identity=key,
                )
            )
        for key in panels.keys() - primary.keys():
            diagnostics.append(
                issue(
                    "panel_only_device",
                    "No matching schematic inventory representation in this scope",
                    panels[key][0]["sources"],
                    identity=key,
                )
            )
        for key in primary.keys() & panels.keys():
            for field in ("manufacturer", "catalog"):
                a = {d.get(field) for d in primary[key] if d.get(field)}
                b = {d.get(field) for d in panels[key] if d.get(field)}
                if a and b and a != b:
                    diagnostics.append(
                        issue(
                            "schematic_panel_conflict",
                            "Schematic and panel inventory values differ",
                            [s for d in primary[key] + panels[key] for s in d["sources"]],
                            identity=key,
                            field=field,
                            schematic=sorted(a),
                            panel=sorted(b),
                        )
                    )
    else:
        diagnostics.append(
            issue("panel_comparison_not_evaluable", "Both schematic and panel inventories are required")
        )
    addresses = collections.defaultdict(list)
    for row in io:
        if row.get("address"):
            module = next((d for d in devices if d["id"] == row["module_device_id"]), {})
            scope = row.get("controller") or "installation:" + (module.get("installation") or "unknown")
            addresses[(scope.casefold(), row["address"].casefold())].append(row)
    for (scope, address), rows in addresses.items():
        identities = {(r["module_device_id"], r.get("terminal_code")) for r in rows}
        if len(identities) > 1:
            diagnostics.append(
                issue(
                    "conflicting_plc_address"
                    if not scope.startswith("installation:")
                    else "potential_plc_address_conflict",
                    "Repeated PLC address; controller scope must be verified",
                    [s for r in rows for s in r["sources"]],
                    address=address,
                    scope=scope,
                    io_ids=[r["id"] for r in rows],
                )
            )
    ips = collections.defaultdict(list)
    for row in network:
        if row.get("device_id") and row.get("ip_address"):
            ips[(row.get("network"), row["ip_address"])].append(row)
    for (scope, address), rows in ips.items():
        if len({r["device_id"] for r in rows}) > 1:
            diagnostics.append(
                issue(
                    "conflicting_network_address" if scope else "potential_network_address_conflict",
                    "Multiple devices document the same address",
                    [s for r in rows for s in r["sources"]],
                    address=address,
                    network=scope,
                )
            )
    # Cross-reference strings can include configurable sheet/line formatting; never guess a missing format.
    sheets = {d.get("sheet") for d in drawings.values() if d.get("sheet")}
    tags = {d.get("tag") for d in devices if d.get("tag")}
    for device in devices:
        for reference in device.get("cross_references", []):
            known = reference in sheets or reference in tags
            diagnostics.append(
                issue(
                    "cross_reference_candidate" if known else "unresolved_cross_reference",
                    "Literal reference matches a known identifier; relationship unverified"
                    if known
                    else "Reference format or target is unresolved; no connection inferred",
                    device["sources"],
                    value=reference,
                    device_id=device["id"],
                )
            )


def equipment_groups(devices, drawings):
    groups = {}
    for device in devices:
        for field in ("installation", "location", "panel", "station"):
            if device.get(field):
                parent = device.get("installation") if field != "installation" else None
                key = (field, parent, device[field])
                group = groups.setdefault(
                    key,
                    {
                        "id": stable_id("group", key),
                        "kind": field,
                        "value": device[field],
                        "installation": parent,
                        "device_ids": [],
                        "relationship_basis": "explicit_attribute_or_report",
                    },
                )
                group["device_ids"].append(device["id"])
        for source in device["sources"]:
            drawing = source.get("drawing") or {}
            context = drawings.get(drawing.get("relative_path"), {}).get("project_context", {})
            for field in ("section", "subsection", "project_folder"):
                if context.get(field):
                    key = ("project_" + field, None, context[field])
                    group = groups.setdefault(
                        key,
                        {
                            "id": stable_id("group", key),
                            "kind": key[0],
                            "value": context[field],
                            "device_ids": [],
                            "relationship_basis": "WDP_project_membership",
                        },
                    )
                    if device["id"] not in group["device_ids"]:
                        group["device_ids"].append(device["id"])
    return list(groups.values())


class ElectricalService:
    def __init__(self, drawings: DrawingService):
        self.drawings, self.config = drawings, drawings.config
        self.state = self.config.state / "electrical"
        for folder in ("projects", "exports"):
            (self.state / folder).mkdir(parents=True, exist_ok=True)
        self.signature = stable_id(
            "analysis", *[(p.name, sha256(p)) for p in sorted(Path(__file__).parent.glob("electrical*.py"))]
        )

    def build(
        self,
        root_id: str,
        drawing_paths: list[str] | None = None,
        electrical_project_path: str | None = None,
        reports: list[dict] | None = None,
        attribute_map: dict | None = None,
        wire_layers: list[str] | None = None,
        tolerance: float = 0.0001,
        include_pdf_candidates: bool = True,
    ) -> dict:
        if root_id not in self.config.roots:
            raise ValueError("Unknown root_id")
        if not math.isfinite(tolerance) or not 0 < tolerance <= 1:
            raise ValueError("tolerance must be greater than zero and at most 1 drawing unit")
        if wire_layers is not None and (
            not isinstance(wire_layers, list)
            or len(wire_layers) > 100
            or any(not isinstance(v, str) or not v for v in wire_layers)
        ):
            raise ValueError("wire_layers must contain at most 100 nonempty layer names")
        mapping, diagnostics, inputs, project = aliases(attribute_map), [], [], None
        root = self.config.roots[root_id]
        if electrical_project_path:
            path = self.config.resolve(root_id, electrical_project_path)
            if path.suffix.lower() != ".wdp":
                raise ValueError("Electrical project input must be a WDP file")
            before = sha256(path)
            project = parse_wdp(path, root)
            inputs.append(
                {
                    "root_id": root_id,
                    "relative_path": electrical_project_path,
                    "sha256": before,
                    "kind": "wdp",
                }
            )
            if sha256(path) != before:
                raise ValueError("WDP changed during reading")
            for member in project["drawings"]:
                if not member["allowed"] or not member["exists"]:
                    diagnostics.append(
                        issue(
                            "unavailable_project_drawing",
                            "WDP member is missing or outside the configured root",
                            member=member,
                        )
                    )
            if drawing_paths is None:
                drawing_paths = [
                    d["relative_path"] for d in project["drawings"] if d["allowed"] and d["exists"]
                ]
        if drawing_paths is None:
            drawing_paths = [
                f["relative_path"]
                for f in self.config.files(root_id)
                if f["extension"] in {".dwg", ".dxf", ".pdf"}
            ]
        if not drawing_paths or len(drawing_paths) > 200 or len(set(drawing_paths)) != len(drawing_paths):
            raise ValueError("Select 1..200 unique drawing paths")
        devices, io, networks, pdf_rows, drawing_info, signals, geometry = [], [], [], [], {}, [], []
        graph = ConnectionGraph()
        for relative_path in drawing_paths:
            doc = self.drawings.load(root_id, relative_path, cached_only=True)
            drawing = (
                drawing_metadata(doc)
                if doc.get("entities") is not None
                else {**doc["source"], "sheet": None, "revision": None}
            )
            if project:
                drawing["project_context"] = next(
                    (d for d in project["drawings"] if d["relative_path"] == relative_path), {}
                )
            drawing_info[relative_path] = drawing
            inputs.append({**doc["source"], "kind": "drawing"})
            for limitation in doc.get("limitations", []):
                diagnostics.append(issue("extraction_limitation", str(limitation), [drawing]))
            if doc.get("format") == "pdf" or relative_path.lower().endswith(".pdf"):
                if include_pdf_candidates:
                    candidates, literals = pdf_candidates(doc)
                    pdf_rows.extend(candidates)
                    networks.extend(literals)
                continue
            physical = list(physical_entities(doc, diagnostics))
            local_devices = []
            for row in physical:
                if row["type"] == "INSERT":
                    device = normalize_instance(row, drawing, mapping)
                    if device:
                        local_devices.append(device)
                        devices.append(device)
                        io.extend(plc_channels(device))
                        networks.extend(network_observations(device, diagnostics))
                        for pin in device["connection_points"]:
                            graph.endpoint(device, pin["terminal"], pin["code"])
                elif row["type"] in {"TEXT", "MTEXT"}:
                    for address in sorted(
                        set(re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", row.get("text", "")))
                    ):
                        try:
                            ipaddress.ip_address(address)
                        except ValueError:
                            continue
                        networks.append(
                            {
                                "id": stable_id("ip_literal", drawing, row["reference_path"], address),
                                "device_id": None,
                                "ip_address": address,
                                "relationship_basis": "unassociated_text_literal",
                                "sources": [
                                    provenance(drawing, row, row["reference_path"], kind="drawing_text")
                                ],
                            }
                        )
            local_signals, scope = add_drawing_geometry(
                graph, doc, drawing, physical, local_devices, diagnostics, wire_layers or [], tolerance
            )
            signals.extend(local_signals)
            geometry.append(scope)
            for reference in doc.get("references", []):
                diagnostics.append(
                    issue(
                        "external_reference_not_traversed",
                        "Declared external reference is not automatically opened",
                        [drawing],
                        reference=reference,
                    )
                )
        if len(reports or []) > 32:
            raise ValueError("At most 32 explicit report inputs are allowed")
        importer = ReportImporter(root_id, root, drawing_info, devices, graph, diagnostics)
        report_data = []
        for specification in reports or []:
            if set(specification) - {"relative_path", "kind", "field_map"}:
                raise ValueError("Unknown report specification field")
            path = self.config.resolve(root_id, specification["relative_path"])
            before = sha256(path)
            rows = parse_report(path, specification["kind"], specification.get("field_map"))
            source = {
                "root_id": root_id,
                "relative_path": specification["relative_path"],
                "sha256": before,
                "kind": specification["kind"],
            }
            if sha256(path) != before:
                raise ValueError("Report changed during reading")
            inputs.append(source)
            report_data.append({"source": source, "rows": rows})
        for report in sorted(report_data, key=lambda r: r["source"]["kind"] != "drawing_map"):
            importer.import_rows(report["source"], report["source"]["kind"], report["rows"])
        io.extend(importer.io)
        networks.extend(importer.network)
        add_associations(graph, devices, diagnostics)
        add_signal_links(graph, signals, diagnostics)
        add_network_peers(graph, devices, networks, diagnostics)
        annotate_wire_numbers(graph, diagnostics)
        consistency(devices, io, networks, drawing_info, diagnostics)
        snapshot = {
            "schema_version": SCHEMA_VERSION,
            "analysis_signature": self.signature,
            "root_id": root_id,
            "inputs": inputs,
            "project": project,
            "drawings": drawing_info,
            "devices": devices,
            "plc_io": io,
            "network": networks,
            "pdf_candidates": pdf_rows,
            "equipment_groups": equipment_groups(devices, drawing_info),
            "checks": diagnostics,
            "geometry_scope": geometry,
            "reports": report_data,
            **graph.snapshot(),
            "options": {
                "drawing_paths": drawing_paths,
                "electrical_project_path": electrical_project_path,
                "reports": reports or [],
                "attribute_map": attribute_map or {},
                "wire_layers": wire_layers or [],
                "tolerance": tolerance,
                "include_pdf_candidates": include_pdf_candidates,
            },
            "scope": "As-of drawing observations and supplied native report assertions; no native engine or physical continuity validation",
        }
        identifier = stable_id("project", self.signature, inputs, snapshot["options"])
        snapshot["project_id"] = identifier
        # Verify every source again after the complete analysis, before publishing a snapshot.
        for source in inputs:
            if sha256(self.config.resolve(source["root_id"], source["relative_path"])) != source["sha256"]:
                raise ValueError("An input changed during project analysis; rebuild from current index")
        snapshot["checks"].sort(key=lambda row: json.dumps(row, sort_keys=True))
        # Diagnostic identities may be tuples in memory; compare exactly the JSON representation we publish.
        snapshot = json.loads(json.dumps(snapshot, ensure_ascii=False, allow_nan=False))
        destination = self.state / "projects" / (identifier + ".json")
        with self.drawings.coordinator.lock("project:" + identifier):
            if destination.exists():
                if json.loads(destination.read_text(encoding="utf-8")) != snapshot:
                    raise ValueError("Immutable project identity conflict; existing snapshot preserved")
            else:
                atomic_json(destination, snapshot)
        return self.summary(snapshot)

    def load(self, project_id):
        if not re.fullmatch(r"project_[a-f0-9]{24}", project_id):
            raise ValueError("Invalid project_id")
        return json.loads((self.state / "projects" / (project_id + ".json")).read_text(encoding="utf-8"))

    def freshness(self, snapshot):
        stale, missing = [], []
        for source in snapshot["inputs"]:
            try:
                path = self.config.resolve(source["root_id"], source["relative_path"])
                if sha256(path) != source["sha256"]:
                    stale.append(source["relative_path"])
            except (ValueError, OSError):
                missing.append(source["relative_path"])
        return {
            "status": "stale" if stale or missing else "current",
            "changed_inputs": stale,
            "unavailable_inputs": missing,
            "analysis_implementation_current": snapshot["analysis_signature"] == self.signature,
        }

    def summary(self, snapshot):
        return {
            "project_id": snapshot["project_id"],
            "root_id": snapshot["root_id"],
            "schema_version": snapshot["schema_version"],
            "counts": {name: len(snapshot[name]) for name in sorted(COLLECTIONS)},
            "drawing_count": len(snapshot["drawings"]),
            "input_count": len(snapshot["inputs"]),
            "check_counts": dict(collections.Counter(i["code"] for i in snapshot["checks"])),
            "freshness": self.freshness(snapshot),
            "scope": snapshot["scope"],
        }

    def get(self, project_id):
        return self.summary(self.load(project_id))

    def query(self, project_id, collection, offset=0, limit=50, query=None, device_id=None, code=None):
        if collection not in COLLECTIONS:
            raise ValueError("Unknown electrical collection")
        snapshot = self.load(project_id)
        rows = snapshot[collection]
        if query:
            rows = [r for r in rows if query.casefold() in json.dumps(r, ensure_ascii=False).casefold()]
        if device_id:
            if collection == "connections":
                nodes = snapshot["nodes"]
                rows = [
                    r
                    for r in rows
                    if any(nodes[r[k]].get("device_id") == device_id for k in ("from_node", "to_node"))
                ]
            else:
                rows = [
                    r
                    for r in rows
                    if device_id in (r.get("id"), r.get("device_id"), r.get("module_device_id"))
                    or device_id in r.get("device_ids", [])
                ]
        if code:
            rows = [r for r in rows if r.get("code") == code or r.get("id") == code]
        return {
            "project_id": project_id,
            "collection": collection,
            "freshness": self.freshness(snapshot),
            **paginate(rows, offset, limit),
        }

    def trace(self, project_id, device_id, terminal=None, domain="electrical", max_depth=40, max_paths=20):
        snapshot = self.load(project_id)
        if not any(d["id"] == device_id for d in snapshot["devices"]):
            raise ValueError("Unknown device_id")
        return {
            "project_id": project_id,
            "device_id": device_id,
            "freshness": self.freshness(snapshot),
            **trace_graph(snapshot, device_id, terminal, domain, max_depth, max_paths),
        }

    def plc_io(self, project_id, offset=0, limit=50, query=None, trace_connections=False):
        result = self.query(project_id, "plc_io", offset, limit, query)
        if trace_connections:
            snapshot = self.load(project_id)
            for row in result["items"]:
                if row.get("record_omitted"):
                    continue
                trace = trace_graph(
                    snapshot,
                    row["module_device_id"],
                    row.get("terminal_code") or row.get("terminal"),
                    max_paths=10,
                )
                row["trace"] = trace
                row["connected_devices"] = sorted({p["destination"]["device_id"] for p in trace["paths"]})
                row["connection_status"] = trace["status"]
                row["wire_numbers"] = sorted(
                    set(row.get("wire_numbers", [])) | {n for p in trace["paths"] for n in p["wire_numbers"]}
                )
        return result

    def compare(self, before_id, after_id, offset=0, limit=100):
        before, after = self.load(before_id), self.load(after_id)
        changes = []
        fields = (
            "tag",
            "role",
            "description",
            "manufacturer",
            "catalog",
            "installation",
            "location",
            "panel",
            "station",
            "controller",
            "rack",
            "slot",
            "channel",
            "ip_address",
            "mac_address",
            "hostname",
            "interface",
            "additional_catalogs",
        )

        def indexed(snapshot):
            result = collections.defaultdict(list)
            for device in snapshot["devices"]:
                key = equipment_key(device) + (
                    device["role"],
                    str(device.get("attributes", {}).get("TERM01", "")),
                )
                result[key].append(
                    {
                        "fields": {k: device.get(k) for k in fields},
                        "id": device["id"],
                        "sources": device["sources"],
                    }
                )
            return result

        a, b = indexed(before), indexed(after)
        for key in sorted(a.keys() | b.keys()):
            old, new = a.get(key, []), b.get(key, [])
            if len(old) > 1 or len(new) > 1:
                if [r["fields"] for r in old] != [r["fields"] for r in new]:
                    changes.append(
                        {
                            "kind": "device",
                            "change": "ambiguous_identity",
                            "identity": key,
                            "before": old,
                            "after": new,
                        }
                    )
            elif not old or not new:
                changes.append(
                    {
                        "kind": "device",
                        "change": "added" if new else "removed",
                        "identity": key,
                        "before": old,
                        "after": new,
                    }
                )
            elif old[0]["fields"] != new[0]["fields"]:
                changes.append(
                    {
                        "kind": "device",
                        "change": "changed",
                        "identity": key,
                        "before": old[0],
                        "after": new[0],
                    }
                )

        def semantic_connections(snapshot):
            by_id = {d["id"]: d for d in snapshot["devices"]}
            result = collections.defaultdict(list)
            for edge in snapshot["connections"]:
                if edge["kind"] not in {
                    "reported_from_to",
                    "reported_plc_connection",
                    "network_connection",
                    "signal_continuation",
                    "wire_segment",
                    "pin_attachment",
                }:
                    continue
                endpoints = []
                for identifier in (edge["from_node"], edge["to_node"]):
                    node = snapshot["nodes"][identifier]
                    device = by_id.get(node.get("device_id"))
                    if device:
                        endpoints.append(
                            [
                                *equipment_key(device),
                                device["role"],
                                node.get("terminal"),
                                node.get("terminal_code"),
                            ]
                        )
                    else:
                        source_drawing = next(
                            (
                                (s.get("drawing") or {}).get("relative_path")
                                for s in node.get("sources", [])
                                if (s.get("drawing") or {}).get("relative_path")
                            ),
                            None,
                        )
                        endpoints.append(
                            [
                                node.get("kind"),
                                node.get("tag"),
                                node.get("layout"),
                                node.get("position"),
                                source_drawing,
                            ]
                        )
                key = json.dumps([edge["kind"], sorted(endpoints, key=str)], sort_keys=True)
                result[key].append(
                    {
                        "wire_numbers": edge["wire_numbers"],
                        "cable": edge.get("cable"),
                        "basis": edge["relationship_basis"],
                        "sources": edge["sources"],
                    }
                )
            return result

        a, b = semantic_connections(before), semantic_connections(after)
        for key in sorted(a.keys() | b.keys()):
            old, new = a.get(key, []), b.get(key, [])

            def semantic(rows):
                return sorted(
                    json.dumps({k: v for k, v in row.items() if k != "sources"}, sort_keys=True)
                    for row in rows
                )

            if semantic(old) != semantic(new):
                changes.append(
                    {
                        "kind": "connection",
                        "change": "changed" if old and new else "added" if new else "removed",
                        "identity": json.loads(key),
                        "before": old,
                        "after": new,
                    }
                )

        def channel_index(snapshot):
            devices = {d["id"]: d for d in snapshot["devices"]}
            result = collections.defaultdict(list)
            for row in snapshot["plc_io"]:
                module = devices.get(row["module_device_id"], {})
                identity = (
                    *equipment_key(module),
                    row.get("terminal_code"),
                    row.get("terminal"),
                    row["relationship_basis"],
                )
                fields = {
                    k: row.get(k)
                    for k in (
                        "controller",
                        "rack",
                        "slot",
                        "channel",
                        "address",
                        "description",
                        "wire_numbers",
                        "cable",
                        "cable_core",
                    )
                }
                result[json.dumps(identity)].append({"fields": fields, "sources": row["sources"]})
            return result

        a, b = channel_index(before), channel_index(after)
        for key in sorted(a.keys() | b.keys()):
            old, new = a.get(key, []), b.get(key, [])
            if sorted(json.dumps(r["fields"], sort_keys=True) for r in old) != sorted(
                json.dumps(r["fields"], sort_keys=True) for r in new
            ):
                changes.append(
                    {
                        "kind": "plc_io",
                        "change": "ambiguous_identity"
                        if len(old) > 1 or len(new) > 1
                        else "changed"
                        if old and new
                        else "added"
                        if new
                        else "removed",
                        "identity": json.loads(key),
                        "before": old,
                        "after": new,
                    }
                )
        return {
            "before_project_id": before_id,
            "after_project_id": after_id,
            "scope": "Qualified equipment identities and documented connection content; ambiguous identities are explicit",
            **paginate(changes, offset, limit),
        }

    def export(self, project_id):
        snapshot = self.load(project_id)
        value = {**snapshot, "export_freshness": self.freshness(snapshot)}
        destination = self.state / "exports" / (project_id + "_" + uuid.uuid4().hex[:12] + ".json")
        atomic_json(destination, value)
        verified = json.loads(destination.read_text(encoding="utf-8"))
        if verified != value:
            raise ValueError("Export readback failed")
        return {
            "project_id": project_id,
            "path": str(destination),
            "sha256": sha256(destination),
            "size_bytes": destination.stat().st_size,
            "freshness": value["export_freshness"],
            "readback_verified": True,
        }
