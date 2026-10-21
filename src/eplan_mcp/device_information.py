"""Device-centric facts and supply paths, preserving reported assertions and observation boundaries."""

from __future__ import annotations

import collections
import ipaddress
import re

from .exports import ExportService, canonical
from .service import paginate

MEDIA = {"electrical", "pneumatic"}
PROFILE_FIELDS = {
    "name",
    "description",
    "device_type",
    "manufacturer",
    "part_number",
    "installation",
    "location",
    "ip_address",
    "interface",
    "port",
    "controller",
    "rack",
    "slot",
    "channel",
    "address",
    "signal",
    "potential",
    "voltage",
    "voltage_unit",
    "pressure",
    "pressure_unit",
}


def reported(row, kind):
    return {
        "kind": kind,
        "fields": row["fields"],
        "source": row["source"],
        "evidence": row.get("evidence", "declared_export_record"),
        **{key: row[key] for key in ("review", "references") if key in row},
        "native_engine_validated": False,
    }


def endpoint(fields, side):
    return (
        fields.get(side + "_tag", ""),
        fields.get(side + "_terminal", ""),
        fields.get(side + "_installation", ""),
        fields.get(side + "_location", ""),
    )


def device_node(fields):
    return (
        fields.get("tag", ""),
        fields.get("terminal", ""),
        fields.get("installation", ""),
        fields.get("location", ""),
    )


def ambiguous_tags(records):
    scopes = collections.defaultdict(set)
    for row in records.get("devices", []):
        f = row["fields"]
        if f.get("tag"):
            scopes[f["tag"]].add((f.get("installation", ""), f.get("location", "")))
    return {tag for tag, values in scopes.items() if len(values) > 1}


class DeviceInformation:
    def __init__(self, drawings):
        self.drawings = drawings
        self.exports = ExportService(drawings)

    def supply(
        self,
        snapshot_id,
        tag,
        medium="electrical",
        terminal=None,
        installation=None,
        location=None,
        max_depth=20,
        max_paths=20,
    ):
        if medium not in MEDIA or not isinstance(tag, str) or not tag:
            raise ValueError("Supply a tag and medium electrical or pneumatic")
        if (
            type(max_depth) is not int
            or not 1 <= max_depth <= 40
            or type(max_paths) is not int
            or not 1 <= max_paths <= 50
        ):
            raise ValueError("max_depth must be 1..40 and max_paths 1..50")
        body = self.exports.load(snapshot_id)
        records = body["records"]
        incoming, nodes, diagnostics = collections.defaultdict(list), set(), []
        for kind in ("connections", "supply_links", "bridges"):
            for ordinal, row in enumerate(records.get(kind, []), 1):
                f = row["fields"]
                if not f.get("medium"):
                    diagnostics.append({"code": "untyped_supply_relationship", "record": reported(row, kind)})
                    continue
                if f.get("medium") != medium:
                    continue
                direction = f.get("flow_direction") or ("source_to_target" if kind == "supply_links" else "")
                a, b = endpoint(f, "source"), endpoint(f, "target")
                if not all((a[0], a[1], b[0], b[1])) or direction not in {
                    "source_to_target",
                    "target_to_source",
                    "bidirectional",
                }:
                    diagnostics.append(
                        {
                            "code": "unusable_supply_relationship",
                            "record": reported(row, kind),
                            "reason": "explicit endpoint tags/terminals and flow direction are required",
                        }
                    )
                    continue
                edge = {"edge_id": f"{kind}:{ordinal}", **reported(row, kind)}
                if direction in {"source_to_target", "bidirectional"}:
                    incoming[b].append((a, edge))
                if direction in {"target_to_source", "bidirectional"}:
                    incoming[a].append((b, edge))
                nodes.update((a, b))
        supplies = [
            reported(r, "supplies")
            for r in records.get("supplies", [])
            if r["fields"].get("medium") == medium
        ]
        nodes.update(device_node(s["fields"]) for s in supplies)
        starts = sorted(
            n
            for n in nodes
            if n[0] == tag
            and (terminal is None or n[1] == terminal)
            and (installation is None or n[2] == installation)
            and (location is None or n[3] == location)
        )
        ambiguous = ambiguous_tags(records)
        queue = collections.deque((node, [], [node]) for node in starts)
        paths, expanded, truncated = [], 0, False
        while queue and len(paths) < max_paths and expanded < 5000:
            node, edges, visited = queue.popleft()
            expanded += 1
            base = {"endpoint": node, "edges": edges, "nodes": visited}
            if node[0] in ambiguous and not node[2] and not node[3]:
                paths.append({**base, "status": "ambiguous_scope", "supplies": []})
                continue
            exact, unbound = [], []
            for supply in supplies:
                candidate = device_node(supply["fields"])
                if candidate == node:
                    exact.append(supply)
                elif candidate[0] == node[0] and candidate[2:] == node[2:] and not candidate[1]:
                    unbound.append(supply)
            if exact or unbound:
                matches = exact or unbound
                status = (
                    "reported_supply_output"
                    if len(exact) == 1
                    else "ambiguous_supply"
                    if len(matches) > 1
                    else "supply_port_unresolved"
                )
                paths.append({**base, "status": status, "supplies": matches})
                continue
            if len(edges) >= max_depth:
                truncated = True
                paths.append({**base, "status": "depth_limit", "supplies": []})
                continue
            options = [
                (parent, edge)
                for parent, edge in incoming.get(node, [])
                if not edges or edge["edge_id"] != edges[-1]["edge_id"]
            ]
            if not options:
                paths.append({**base, "status": "unresolved_upstream", "supplies": []})
                continue
            for parent, edge in options:
                if parent in visited:
                    paths.append({**base, "status": "cycle", "cycle_edge": edge, "supplies": []})
                    if len(paths) >= max_paths:
                        break
                else:
                    if len(queue) >= 5000:
                        truncated = True
                        continue
                    queue.append((parent, edges + [edge], visited + [parent]))
        truncated = truncated or bool(queue) or len(paths) >= max_paths
        complete = (
            bool(paths)
            and not truncated
            and not diagnostics
            and all(p["status"] == "reported_supply_output" for p in paths)
        )
        return {
            "snapshot_id": snapshot_id,
            "tag": tag,
            "medium": medium,
            "status": "reported_paths_resolved"
            if complete
            else "unresolved_start"
            if not starts
            else "incomplete",
            "complete_for_supplied_relationships": complete,
            "truncated": truncated,
            "paths": paths,
            "diagnostics": paginate(diagnostics, 0, 10),
            "sources": self.exports.freshness(body),
            "limitations": [
                "Flow is followed only when declared; ordinary source/target ordering does not prove energy flow.",
                "Internal device/terminal bridges are never invented; reported direction does not establish live valve/switch state.",
                "Completeness is limited to supplied records, not the project or physical installation.",
            ],
        }

    def profile(self, snapshot_id, tag, installation=None, location=None, offset=0, limit=50):
        if not isinstance(tag, str) or not tag:
            raise ValueError("Supply an exact device tag")
        body = self.exports.load(snapshot_id)
        rows, facts, scopes = [], collections.defaultdict(list), set()
        for kind in ("devices", "plc_io", "network", "supplies"):
            for row in body["records"].get(kind, []):
                f = row["fields"]
                if f.get("tag") != tag:
                    continue
                if installation is not None and f.get("installation", "") != installation:
                    continue
                if location is not None and f.get("location", "") != location:
                    continue
                rows.append(reported(row, kind))
                if kind == "devices" or f.get("installation") or f.get("location"):
                    scopes.add((f.get("installation", ""), f.get("location", "")))
                for name in PROFILE_FIELDS:
                    if f.get(name):
                        fact = {"value": f[name], "source": row["source"], "kind": kind}
                        fact.update(
                            {key: row[key] for key in ("evidence", "review", "references") if key in row}
                        )
                        fact["context"] = {
                            k: f[k]
                            for k in (
                                "interface",
                                "port",
                                "controller",
                                "rack",
                                "slot",
                                "channel",
                                "address",
                                "terminal",
                                "medium",
                            )
                            if f.get(k)
                        }
                        if name == "ip_address":
                            try:
                                ipaddress.ip_address(f[name])
                                fact["valid_ip_literal"] = True
                            except ValueError:
                                fact["valid_ip_literal"] = False
                        facts[name].append(fact)
        conflicts = []
        for name in (
            "name",
            "manufacturer",
            "part_number",
            "device_type",
            "ip_address",
            "voltage",
            "pressure",
        ):
            groups = collections.defaultdict(set)
            for fact in facts.get(name, []):
                groups[canonical(fact["context"])].add(fact["value"])
            for context, values in sorted(groups.items()):
                if len(values) > 1:
                    conflicts.append(
                        {
                            "field": name,
                            "context": context,
                            "values": sorted(values)[:20],
                            "value_count": len(values),
                            "review_required": True,
                        }
                    )
        # Do not combine facts across known duplicate tag scopes.
        ambiguous = len(scopes) > 1
        supply_summary = {}
        if not ambiguous:
            for medium in sorted(MEDIA):
                traced = self.supply(
                    snapshot_id,
                    tag,
                    medium,
                    installation=installation,
                    location=location,
                    max_depth=15,
                    max_paths=5,
                )
                candidates = {canonical(s): s for p in traced["paths"] for s in p["supplies"]}
                supply_summary[medium] = {
                    "status": traced["status"],
                    "truncated": traced["truncated"],
                    "supplies": list(candidates.values()),
                    "complete_for_supplied_relationships": traced["complete_for_supplied_relationships"],
                }
        device_found = any(r["kind"] == "devices" for r in rows)
        return {
            "snapshot_id": snapshot_id,
            "tag": tag,
            "status": "ambiguous_scope"
            if ambiguous
            else "reported_device"
            if device_found
            else "partial_records"
            if rows
            else "not_found",
            "scopes": sorted(scopes)[:20],
            "scope_count": len(scopes),
            "facts": {} if ambiguous else {k: v[:10] for k, v in sorted(facts.items())},
            "fact_counts": {} if ambiguous else {k: len(v) for k, v in sorted(facts.items())},
            "conflicts": conflicts,
            "supplies": supply_summary,
            "sources": self.exports.freshness(body),
            "association_basis": "exact tag and explicitly selected scope within supplied records; no global coverage assertion",
            **paginate(rows, offset, limit),
        }


IP_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
LABEL_PATTERNS = {
    "power": re.compile(r"power\s+suppl(?:y|ies)|\b\d+(?:[.,]\d+)?\s*V\s*(?:AC|DC)\b", re.I),
    "air": re.compile(
        r"\bair\s+(?:suppl(?:y|ies)|feed|prep(?:aration)?(?:\s+unit)?|manifold|drop|lockout)\b"
        r"|\bplant\s+air\b|\bdump\s+valve\b|pneumatic|compressed\s+air"
        r"|\b\d+(?:[.,]\d+)?\s*(?:bar|psi|kpa|mpa)\b|pressure\s+regulator",
        re.I,
    ),
    "io": re.compile(
        r"(?<![\w])(?:%?[IQ](?:[XBWD])?\d+(?:\.\d+)?"
        r"|(?:DI|DO|AI|AO|GI|GO|UI|UO)\[\d+\])(?![\w.\[\]])",
        re.I,
    ),
}


def collect_evidence(
    drawings, root_id, drawing_paths, device_query=None, category=None, radius=80, offset=0, limit=50
):
    if (
        not isinstance(drawing_paths, list)
        or not 1 <= len(drawing_paths) <= 100
        or len(set(drawing_paths)) != len(drawing_paths)
    ):
        raise ValueError("Select 1..100 unique drawing paths")
    if category not in {None, "device", "ip", "power", "air", "io"}:
        raise ValueError("category must be device, ip, power, air or io")
    if not isinstance(radius, (int, float)) or not 0 <= radius <= 500:
        raise ValueError("radius must be 0..500 PDF points")
    if device_query is not None and (
        not isinstance(device_query, str) or not device_query.strip() or len(device_query) > 200
    ):
        raise ValueError("device_query must be a nonempty literal up to 200 characters")
    results, coverage = [], []
    for path in drawing_paths:
        try:
            document = drawings.load(root_id, path, cached_only=True)
        except (OSError, ValueError) as error:
            coverage.append({"relative_path": path, "status": "unavailable", "error": str(error)[:500]})
            continue
        texts = document.get("text", [])
        anchors = [
            (i, r)
            for i, r in enumerate(texts)
            if device_query and device_query.casefold() in r.get("text", "").casefold()
        ]
        if len(anchors) > 2000:
            raise ValueError("More than 2000 device anchors in a file; narrow device_query")
        by_page = collections.defaultdict(list)
        for index, anchor in anchors:
            by_page[anchor.get("page")].append((index, anchor))
        coverage.append(
            {
                "source": document["source"],
                "status": "extracted_text",
                "anchor_count": len(anchors),
                "ocr_candidate_pages": [
                    p["page"] for p in document.get("pages", []) if p.get("ocr_candidate")
                ],
            }
        )
        for index, row in enumerate(texts):
            text = row.get("text", "")
            anchor_ids = []
            if device_query:
                for anchor_index, anchor in by_page[row.get("page")]:
                    if anchor_index == index:
                        anchor_ids.append(anchor_index)
                    elif row.get("type") == "PDF_TEXT" and anchor.get("bbox") and row.get("bbox"):
                        a, b = anchor["bbox"], row["bbox"]
                        dx = max(a[0] - b[2], b[0] - a[2], 0)
                        dy = max(a[1] - b[3], b[1] - a[3], 0)
                        if dx * dx + dy * dy <= radius * radius:
                            anchor_ids.append(anchor_index)
                if not anchor_ids:
                    continue
            matches = []
            if device_query and device_query.casefold() in text.casefold():
                matches.append(("device", device_query))
            for value in IP_PATTERN.findall(text):
                try:
                    ipaddress.ip_address(value)
                    matches.append(("ip", value))
                except ValueError:
                    pass
            for name, pattern in LABEL_PATTERNS.items():
                matches.extend((name, m.group()) for m in pattern.finditer(text))
            for name, value in sorted(set(matches)):
                if category is not None and name != category:
                    continue
                results.append(
                    {
                        "category": name,
                        "value": value,
                        "text": text,
                        "record_index": index,
                        "location": {
                            k: row[k] for k in ("page", "bbox", "handle", "layout", "layer") if k in row
                        },
                        "source": document["source"],
                        "device_anchor_records": anchor_ids[:20],
                        "anchor_records_truncated": len(anchor_ids) > 20,
                        "association": "literal_or_nearby_text_candidate"
                        if device_query
                        else "unassociated_text_candidate",
                        "establishes_device_identity_or_supply": False,
                    }
                )
                if len(results) > 100_000:
                    raise ValueError("Evidence exceeds 100000 rows; narrow the file selection/query")
    return {
        "root_id": root_id,
        "device_query": device_query,
        "coverage": coverage,
        "candidate_counts": dict(collections.Counter(r["category"] for r in results)),
        "limitations": [
            "Text proximity and repeated tags do not establish device membership, feed direction or connectivity.",
            "Part catalog descriptions and revision notes can match supply labels.",
            "I/O literals can repeat across controllers or manifolds; address text alone does not identify a channel owner.",
            "Evidence covers extracted text only; raster/unsupported content can be missing.",
        ],
        **paginate(results, offset, limit),
    }
