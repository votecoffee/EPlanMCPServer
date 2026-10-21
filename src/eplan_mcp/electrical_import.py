"""Bind declared native report records to drawings without assuming DWGIX is drawing order."""

from __future__ import annotations

import re
from pathlib import Path

from .electrical_model import TYPE_RULES, issue, stable_id


class ReportImporter:
    def __init__(self, root_id, root, drawings, devices, graph, diagnostics):
        self.root_id, self.root = root_id, root
        self.drawings, self.devices, self.graph, self.diagnostics = drawings, devices, graph, diagnostics
        self.drawing_map, self.reported_devices = {}, {}
        self.io, self.network = [], []

    def drawing_reference(self, filename: str) -> dict | None:
        normalized = filename.replace("\\", "/")
        candidate = Path(normalized)
        if candidate.is_absolute():
            try:
                normalized = candidate.relative_to(self.root).as_posix()
            except ValueError:
                return None
        matches = [d for name, d in self.drawings.items() if name.casefold() == normalized.casefold()]
        return matches[0] if len(matches) == 1 else None

    def source(
        self, report: dict, row: dict, prefix="", *, handle_key=None, file_key=None, dwgix_key=None
    ) -> dict:
        fields = row["fields"]
        filename = fields.get(file_key or prefix + "FILENAME") or fields.get(prefix + "FILE")
        dwgix = fields.get(dwgix_key or prefix + "DWGIX")
        if not filename and dwgix:
            filename = self.drawing_map.get(dwgix)
        drawing = self.drawing_reference(filename) if filename else None
        handle = fields.get(handle_key or prefix + "HDL") or None
        source = {
            "kind": "autocad_electrical_report",
            "native_relationship": True,
            "native_engine_validated": False,
            "report": report,
            "row": row["row"],
            "report_role": prefix or "component",
            "drawing": drawing,
            "object_handle": handle,
            "sheet": (drawing or {}).get("sheet") or fields.get(prefix + "SH") or fields.get("SH"),
            "reported_sheet": fields.get(prefix + "SH") or fields.get("SH"),
            "reference_path": [handle] if handle else [],
            "reference": f"{report['root_id']}/{report['relative_path']}#row={row['row']}&role={prefix}",
            "drawing_binding": "declared_filename_or_FILETIME_mapping" if drawing else "unresolved",
            "drawing_freshness": "not proven by report; export has no authenticated drawing hash",
        }
        if not drawing:
            self.diagnostics.append(
                issue(
                    "native_drawing_reference_unresolved",
                    "Report row is retained, but its DWGIX/filename has no supplied drawing mapping",
                    [source],
                    dwgix=dwgix,
                    declared_filename=filename,
                )
            )
        return source

    def device(self, values: dict, source: dict, role: str, identity_extra=None) -> dict | None:
        if not values.get("tag"):
            return None
        drawing, handle = source.get("drawing"), source.get("object_handle")
        candidates = []
        if drawing and handle:
            for device in self.devices:
                for original in device["sources"]:
                    if (original.get("drawing") or {}).get("relative_path") == drawing["relative_path"] and (
                        original.get("object_handle") or ""
                    ).casefold() == handle.casefold():
                        candidates.append(device)
                        break
        key = (
            source["report"]["sha256"],
            role,
            values.get("tag"),
            values.get("installation"),
            values.get("location"),
            drawing["relative_path"] if drawing else None,
            handle,
            identity_extra,
        )
        target = candidates[0] if len(candidates) == 1 else self.reported_devices.get(key)
        if len(candidates) > 1:
            self.diagnostics.append(
                issue("ambiguous_report_handle", "Handle occurs in multiple nested placements", [source])
            )
        if target is None:
            description = values.get("description") or ""
            category = next(
                (name for name, pattern in TYPE_RULES if re.search(pattern, description, re.I)),
                "io_module" if role == "plc_module" else "terminal" if role == "terminal" else "unclassified",
            )
            target = {
                "id": stable_id("reported_device", key),
                "tag": values["tag"],
                "role": role,
                "device_type": category,
                "attributes": {},
                "terminals": [],
                "connection_points": [],
                "cross_references": [],
                "sources": [],
                "field_sources": {"device_type": {"kind": "classification_rule", "interpreted": True}},
                "reported_observations": [],
            }
            self.devices.append(target)
        for field, value in values.items():
            if not value:
                continue
            if target.get(field) and target[field] != value:
                self.diagnostics.append(
                    issue(
                        "report_attribute_conflict",
                        "Reported and observed field values disagree",
                        target["sources"] + [source],
                        field=field,
                        observed=target[field],
                        reported=value,
                        device_id=target["id"],
                    )
                )
            elif not target.get(field):
                target[field] = value
                target["field_sources"][field] = {
                    "kind": "native_report_field",
                    "interpreted": False,
                    "report_reference": source["reference"],
                }
        if source not in target["sources"]:
            target["sources"].append(source)
        target.setdefault("reported_observations", []).append({"values": values, "source": source})
        self.reported_devices[key] = target
        return target

    @staticmethod
    def values(fields, prefix=""):
        return {
            "tag": fields.get(prefix + "TAG"),
            "description": " ".join(
                fields[prefix + k] for k in ("DESC1", "DESC2", "DESC3") if fields.get(prefix + k)
            )
            or None,
            "manufacturer": fields.get(prefix + "MFG"),
            "catalog": fields.get(prefix + "CAT"),
            "installation": fields.get(prefix + "INST"),
            "location": fields.get(prefix + "LOC"),
        }

    def import_rows(self, report: dict, kind: str, rows: list):
        for row in rows:
            fields = row["fields"]
            if kind == "drawing_map":
                identifier, filename = fields["DWGIX"], fields["FILENAME"]
                if identifier in self.drawing_map and self.drawing_map[identifier] != filename:
                    raise ValueError("Conflicting FILETIME drawing mappings")
                self.drawing_map[identifier] = filename
            elif kind in {"components", "panel", "network"}:
                source = self.source(report, row, file_key="FILENAME")
                role = "panel" if kind == "panel" else "child" if fields.get("P1C2") == "2" else "schematic"
                device = self.device(self.values(fields), source, role)
                if device and kind == "network":
                    self.network.append(
                        {
                            "id": stable_id("native_net", source),
                            "device_id": device["id"],
                            "tag": device["tag"],
                            "ip_address": fields.get("IP_ADDRESS"),
                            "mac_address": fields.get("MAC_ADDRESS"),
                            "hostname": fields.get("HOSTNAME"),
                            "network": fields.get("NETWORK"),
                            "interface": fields.get("INTERFACE"),
                            "ports": [{"port": fields["PORT"], "peer": fields.get("PEER")}]
                            if fields.get("PORT")
                            else [],
                            "sources": [source],
                            "relationship_basis": "native_report",
                        }
                    )
            elif kind == "plc_connections":
                self.plc_connection(report, row)
            elif kind == "from_to":
                endpoints, sources = [], []
                for prefix in ("FROM_", "TO_"):
                    source = self.source(report, row, prefix)
                    device = self.device(self.values(fields, prefix), source, "schematic")
                    sources.append(source)
                    if device:
                        endpoints.append(self.graph.endpoint(device, fields.get(prefix + "TERM")))
                if len(endpoints) == 2:
                    self.graph.connect(
                        *endpoints,
                        "reported_from_to",
                        "native_report",
                        sources,
                        wire_numbers=[fields.get("WIRENO")],
                        cable=fields.get("CBL"),
                        details={"cable_core": fields.get("CBLWC"), "report_fields": fields},
                    )
                else:
                    self.diagnostics.append(
                        issue("incomplete_report_connection", "From/To row lacks an endpoint tag", sources)
                    )

    def plc_connection(self, report, row):
        fields = row["fields"]
        plc_source = self.source(report, row, "PLC")
        plc = self.device(self.values(fields, "PLC"), plc_source, "plc_module")
        if not plc:
            self.diagnostics.append(issue("missing_plc_tag", "PLC row lacks a module tag", [plc_source]))
            return
        endpoint = self.graph.endpoint(
            plc, fields.get("PLCTERM"), fields.get("PLCTERMCODE") or fields.get("PLCADDR")
        )
        connected, sources, terminal_detail = [], [plc_source], None
        if fields.get("CMPTAG"):
            component_source = self.source(report, row, "CMP")
            component = self.device(self.values(fields, "CMP"), component_source, "schematic")
            if component:
                connected.append(component["id"])
                sources.append(component_source)
                self.graph.connect(
                    endpoint,
                    self.graph.endpoint(component, fields.get("CMPTERM")),
                    "reported_plc_connection",
                    "native_report",
                    sources,
                    wire_numbers=[fields.get("PLCWNUM")],
                    cable=fields.get("CBL"),
                    details={
                        "terminal_strip": {k: v for k, v in fields.items() if k.startswith("TERM")},
                        "cable_core": fields.get("CBLWC"),
                        "segment_order": "not provided by PLC component report",
                    },
                )
        if fields.get("TERMTAG"):
            terminal_source = self.source(report, row, "TERM")
            terminal = self.device(
                self.values(fields, "TERM"), terminal_source, "terminal", fields.get("TERMTERM")
            )
            if terminal:
                terminal_detail = {
                    "device_id": terminal["id"],
                    "number": fields.get("TERMTERM"),
                    "source": terminal_source,
                }
                if not connected:
                    connected.append(terminal["id"])
                    self.graph.connect(
                        endpoint,
                        self.graph.endpoint(terminal, fields.get("TERMTERM")),
                        "reported_plc_connection",
                        "native_report",
                        [plc_source, terminal_source],
                        wire_numbers=[fields.get("PLCWNUM")],
                        cable=fields.get("CBL"),
                    )
        self.io.append(
            {
                "id": stable_id("reported_io", report, row["row"]),
                "module_device_id": plc["id"],
                "module_tag": fields["PLCTAG"],
                "controller": fields.get("CONTROLLER"),
                "rack": fields.get("RACK"),
                "slot": fields.get("SLOT"),
                "channel": fields.get("CHANNEL"),
                "terminal_code": fields.get("PLCTERMCODE"),
                "address": fields["PLCADDR"],
                "terminal": fields.get("PLCTERM"),
                "description": " ".join(
                    fields[k]
                    for k in ("PLCDESCA", "PLCDESCB", "PLCDESCC", "PLCDESCD", "PLCDESCE")
                    if fields.get(k)
                )
                or None,
                "connected_devices": connected,
                "wire_numbers": [fields["PLCWNUM"]] if fields.get("PLCWNUM") else [],
                "terminal_strip": terminal_detail,
                "cable": fields.get("CBL"),
                "cable_core": fields.get("CBLWC"),
                "sources": sources,
                "relationship_basis": "native_report",
                "connection_status": "reported" if connected else "incomplete",
                "inferred_fields": {},
            }
        )
