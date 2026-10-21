"""Evidence-labelled connection graphs. Association never implies electrical continuity."""

from __future__ import annotations

import collections
import fnmatch
import math
import re

from ezdxf.math import Matrix44

from .electrical_model import attribute_values, issue, provenance, stable_id


class ConnectionGraph:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}

    def endpoint(self, device: dict, terminal: str | None = None, code: str | None = None) -> str:
        if code is None and terminal is not None:
            existing = [
                n
                for n in self.nodes.values()
                if n.get("device_id") == device["id"] and n.get("terminal") == terminal
            ]
            if len(existing) == 1:
                return existing[0]["id"]
        identifier = stable_id("node", device["id"], str(code if code is not None else terminal or ""))
        self.nodes.setdefault(
            identifier,
            {
                "id": identifier,
                "device_id": device["id"],
                "tag": device.get("tag"),
                "installation": device.get("installation"),
                "location": device.get("location"),
                "terminal": terminal,
                "terminal_code": code,
                "sources": device["sources"],
                "kind": "device_terminal",
            },
        )
        return identifier

    def marker(self, source: dict, *, tag=None, kind="signal") -> str:
        identifier = stable_id("marker", source, kind)
        self.nodes.setdefault(
            identifier, {"id": identifier, "device_id": None, "tag": tag, "sources": [source], "kind": kind}
        )
        return identifier

    def connect(
        self,
        a: str,
        b: str,
        kind: str,
        basis: str,
        sources: list,
        *,
        wire_numbers=None,
        cable=None,
        domains=None,
        details=None,
    ) -> str:
        if a == b:
            return ""
        wire_numbers = sorted(set(n for n in wire_numbers or [] if n))
        identifier = stable_id("connection", sorted((a, b)), kind, basis, wire_numbers, cable)
        row = self.edges.setdefault(
            identifier,
            {
                "id": identifier,
                "from_node": a,
                "to_node": b,
                "kind": kind,
                "relationship_basis": basis,
                "native_relationship": basis == "native_report",
                "sources": [],
                "wire_numbers": wire_numbers,
                "cable": cable,
                "domains": domains if domains is not None else ["electrical"],
                "details": details or {},
            },
        )
        for source in sources:
            if source not in row["sources"]:
                row["sources"].append(source)
        return identifier

    def snapshot(self) -> dict:
        return {"nodes": self.nodes, "connections": list(self.edges.values())}


def add_associations(graph: ConnectionGraph, devices: list, diagnostics: list):
    primary = collections.defaultdict(list)
    terminal_links = collections.defaultdict(list)
    for device in devices:
        key = tuple((device.get(k) or "").casefold() for k in ("installation", "location", "tag"))
        if device["role"] in {"schematic", "ordinary_block", "plc_module"} and device.get("tag"):
            primary[key].append(device)
        if device.get("attributes", {}).get("LINKTERM"):
            terminal_links[device["attributes"]["LINKTERM"]].append(device)
    for device in devices:
        if device["role"] not in {"child", "panel"}:
            continue
        key = tuple((device.get(k) or "").casefold() for k in ("installation", "location", "tag"))
        matches = primary[key]
        if len(matches) == 1:
            parent = matches[0]
            graph.connect(
                graph.endpoint(device),
                graph.endpoint(parent),
                "representation_of",
                "attribute_assertion",
                device["sources"] + parent["sources"],
                domains=[],
            )
        elif device["role"] == "child":
            diagnostics.append(
                issue(
                    "unresolved_parent" if not matches else "ambiguous_parent",
                    "Child tag does not identify exactly one primary occurrence",
                    device["sources"],
                    device_id=device["id"],
                    candidate_ids=[d["id"] for d in matches],
                )
            )
    for code, linked in terminal_links.items():
        for device in linked[1:]:
            graph.connect(
                graph.endpoint(linked[0]),
                graph.endpoint(device),
                "terminal_association",
                "attribute_assertion",
                linked[0]["sources"] + device["sources"],
                domains=[],
                details={"LINKTERM": code, "continuity": "not established; may be separate terminal levels"},
            )


def add_network_peers(graph: ConnectionGraph, devices: list, networks: list, diagnostics: list):
    by_id = {device["id"]: device for device in devices}
    by_tag = collections.defaultdict(list)
    for device in devices:
        if device.get("tag") and device["role"] != "pdf_candidate":
            by_tag[device["tag"].casefold()].append(device)
    for row in networks:
        if row.get("device_id") not in by_id:
            continue
        device = by_id[row["device_id"]]
        for port in row.get("ports", []):
            if not port.get("peer"):
                continue
            candidates = [
                d
                for d in by_tag[port["peer"].casefold()]
                if d.get("installation") == device.get("installation")
                and d.get("location") == device.get("location")
                and d["role"] != "panel"
            ]
            if len(candidates) != 1:
                diagnostics.append(
                    issue(
                        "unresolved_network_peer" if not candidates else "ambiguous_network_peer",
                        "Port peer does not identify one device in the same equipment scope",
                        row["sources"],
                        peer=port["peer"],
                        port=port["port"],
                        device_id=device["id"],
                    )
                )
                continue
            graph.connect(
                graph.endpoint(device, port["port"], "PORT:" + port["port"]),
                graph.endpoint(candidates[0]),
                "network_connection",
                "native_report"
                if row.get("relationship_basis") == "native_report"
                else "attribute_assertion",
                row["sources"] + candidates[0]["sources"],
                domains=["network"],
            )


def select_wire_layers(doc: dict, physical: list, explicit: list[str]) -> tuple[set[str], str, list[str]]:
    available = {layer["name"].casefold(): layer["name"] for layer in doc["layers"]}
    if explicit:
        return (
            {name.casefold() for name in explicit if name.casefold() in available},
            "explicit_configuration",
            [],
        )
    declared = set()
    unsupported = []
    for row in physical:
        if row["type"] == "INSERT" and row["properties"].get("name", "").upper() == "WD_M":
            attrs, _ = attribute_values(row)
            for pattern in re.split(r"[,;|]", attrs.get("WIRELAYS", "")):
                pattern = pattern.strip(' "').casefold()
                if not pattern:
                    continue
                if pattern in available:
                    declared.add(pattern)
                elif any(c in pattern for c in "#@.~[]`"):
                    unsupported.append(pattern)
                else:
                    declared.update(name for name in available if fnmatch.fnmatchcase(name, pattern))
    if declared:
        return declared, "WD_M.WIRELAYS_attribute_simple_wildcards", unsupported
    if unsupported:
        return set(), "unsupported_WD_M.WIRELAYS_patterns", unsupported
    return (
        {name for name in available if re.search(r"wire|wiring|awg|pneu[_ ]?tube", name, re.I)},
        "layer_name_interpretation",
        [],
    )


def add_drawing_geometry(
    graph: ConnectionGraph,
    doc: dict,
    drawing: dict,
    physical: list,
    devices: list,
    diagnostics: list,
    explicit_layers: list[str],
    tolerance: float,
):
    layers, layer_basis, unsupported_patterns = select_wire_layers(doc, physical, explicit_layers)
    if unsupported_patterns:
        diagnostics.append(
            issue(
                "unsupported_wire_layer_patterns",
                "Configure explicit wire layers for unsupported native wildcard syntax",
                [drawing],
                patterns=unsupported_patterns,
            )
        )
    segments, pins, dots, labels, signals = [], [], [], [], []
    by_path = {
        tuple(d["sources"][0]["reference_path"]): d
        for d in devices
        if d["sources"][0].get("drawing", {}).get("relative_path") == drawing["relative_path"]
    }
    for row in physical:
        matrix = Matrix44(row["world_matrix"])
        source = provenance(drawing, row, row["reference_path"], kind="geometric_interpretation")
        if row["type"] == "INSERT":
            attrs, _ = attribute_values(row)
            name = row["properties"].get("name", "").upper()
            device = by_path.get(tuple(row["reference_path"]))
            if device:
                for pin in device["connection_points"]:
                    if pin["position"]:
                        pins.append(
                            (
                                row["layout"],
                                pin["position"],
                                graph.endpoint(device, pin["terminal"], pin["code"]),
                            )
                        )
            if attrs.get("SIGCODE"):
                marker = graph.marker(source, tag=attrs["SIGCODE"], kind="signal")
                point = next(
                    (
                        a.get("world_position")
                        for a in row["attributes"]
                        if re.fullmatch(r"X[1248]TERM01", a["tag"].upper())
                    ),
                    None,
                )
                if point:
                    pins.append((row["layout"], point, marker))
                role = (
                    "source"
                    if re.fullmatch(r"[HV]A\d+S\d+", name)
                    else ("destination" if re.fullmatch(r"[HV]A\d+D\d+", name) else "unknown")
                )
                signals.append(
                    {
                        "node": marker,
                        "code": attrs["SIGCODE"],
                        "role": role,
                        "source": source,
                        "wire_number": attrs.get("WIRENO") or attrs.get("WIRENOF"),
                    }
                )
            if name == "WDDOT":
                dots.append((row["layout"], row["world_position"]))
            if attrs.get("WIRENO") or attrs.get("WIRENOF"):
                labels.append(
                    (
                        row["layout"],
                        row["world_position"],
                        attrs.get("WIRENO") or attrs.get("WIRENOF"),
                        source,
                    )
                )
            continue
        if row["effective_layer"].casefold() not in layers:
            continue
        points = []
        if row["type"] == "LINE":
            points = [list(matrix.transform(row["properties"][key])) for key in ("start", "end")]
        elif row["type"] == "LWPOLYLINE":
            if any(vertex[4] for vertex in row["vertices"]):
                diagnostics.append(
                    issue(
                        "curved_wire_not_traced",
                        "Bulged polyline is not treated as a straight wire",
                        [source],
                    )
                )
                continue
            elevation = row["properties"].get("elevation", 0)
            points = [list(matrix.transform((v[0], v[1], elevation))) for v in row["vertices"]]
            if row.get("closed") and points:
                points.append(points[0])
        for a, b in zip(points, points[1:]):
            if math.dist(a, b) > tolerance:
                segments.append((row["layout"], a, b, source))
    if len(segments) > 30000:
        raise ValueError("Wire geometry exceeds 30000 segments; select narrower wire layers or drawing scope")
    if not layers:
        diagnostics.append(
            issue(
                "wire_layers_unknown", "No eligible wire layers; geometric tracing is unavailable", [drawing]
            )
        )
    # Candidate points consist of endpoints, pins and explicit junction dots. Unmarked interior crossings stay separate.
    points = [(layout, p) for layout, a, b, _ in segments for p in (a, b)] + dots
    if not segments:
        return signals, {
            "drawing": drawing["relative_path"],
            "wire_layers": sorted(layers),
            "basis": layer_basis,
            "unsupported_wire_layer_patterns": unsupported_patterns,
            "segments": 0,
            "unattached_pins": len(pins),
        }
    all_x = [p[0] for _, p in points]
    all_y = [p[1] for _, p in points]
    extent = max(max(all_x) - min(all_x), max(all_y) - min(all_y), tolerance * 100)
    cell_size = max(tolerance * 100, extent / math.sqrt(len(segments)))
    grid, long_segments = collections.defaultdict(set), []
    for index, (layout_name, a, b, _) in enumerate(segments):
        x0, x1 = (
            math.floor((min(a[0], b[0]) - tolerance) / cell_size),
            math.floor((max(a[0], b[0]) + tolerance) / cell_size),
        )
        y0, y1 = (
            math.floor((min(a[1], b[1]) - tolerance) / cell_size),
            math.floor((max(a[1], b[1]) + tolerance) / cell_size),
        )
        if (x1 - x0 + 1) * (y1 - y0 + 1) > 2000:
            long_segments.append(index)
            continue
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                grid[layout_name, x, y].add(index)
        if len(grid) > 200000:
            raise ValueError("Geometry spatial index exceeds budget")
    vertex_bins, split_points, attached = collections.defaultdict(list), collections.defaultdict(dict), {}

    def vertex(layout_name, point):
        key = tuple(math.floor(v / tolerance) for v in point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for identifier, position in vertex_bins[
                        (layout_name, key[0] + dx, key[1] + dy, key[2] + dz)
                    ]:
                        if math.dist(point, position) <= tolerance:
                            return identifier
        identifier = stable_id("vertex", drawing, layout_name, point)
        graph.nodes[identifier] = {
            "id": identifier,
            "device_id": None,
            "kind": "wire_vertex",
            "position": list(point),
            "layout": layout_name,
            "sources": [],
        }
        vertex_bins[(layout_name, *key)].append((identifier, point))
        return identifier

    def place(layout_name, point, allow_junction=False):
        candidates = grid.get(
            (layout_name, math.floor(point[0] / cell_size), math.floor(point[1] / cell_size)), set()
        )
        hits = []
        for index in set(candidates) | set(long_segments):
            layer_layout, a, b, _ = segments[index]
            if layer_layout != layout_name:
                continue
            delta = [b[i] - a[i] for i in range(3)]
            length2 = sum(v * v for v in delta)
            t = sum((point[i] - a[i]) * delta[i] for i in range(3)) / length2
            if not -tolerance / math.sqrt(length2) <= t <= 1 + tolerance / math.sqrt(length2):
                continue
            t = min(1, max(0, t))
            closest = [a[i] + t * delta[i] for i in range(3)]
            if math.dist(point, closest) <= tolerance:
                hits.append((index, t, delta))
        # A label or pin at an unmarked interior crossing cannot identify a unique wire.
        explicit_dot = any(
            layout_name == layout and math.dist(point, position) <= tolerance for layout, position in dots
        )
        if not allow_junction and not explicit_dot and len(hits) > 1 and all(0 < t < 1 for _, t, _ in hits):
            left = hits[0][2]
            for _, _, right in hits[1:]:
                cross = [
                    left[1] * right[2] - left[2] * right[1],
                    left[2] * right[0] - left[0] * right[2],
                    left[0] * right[1] - left[1] * right[0],
                ]
                if math.sqrt(sum(v * v for v in cross)) > tolerance * math.sqrt(
                    sum(v * v for v in left) * sum(v * v for v in right)
                ):
                    return None
        identifier = vertex(layout_name, point) if hits else None
        for index, t, _ in hits:
            split_points[index][identifier] = t
        return identifier

    for layout_name, point in points:
        place(layout_name, point, allow_junction=True)
    for layout_name, point in [pin[:2] for pin in pins] + [label[:2] for label in labels]:
        place(layout_name, point)
    for index, (layout_name, a, b, source) in enumerate(segments):
        # Endpoints are guaranteed even when no pin is present.
        split_points[index].setdefault(vertex(layout_name, a), 0)
        split_points[index].setdefault(vertex(layout_name, b), 1)
        ordered = sorted(split_points[index], key=split_points[index].get)
        for left, right in zip(ordered, ordered[1:]):
            graph.connect(
                left,
                right,
                "wire_segment",
                "geometric_interpretation",
                [source],
                details={"layer_basis": layer_basis, "tolerance_drawing_units": tolerance},
            )
    unattached = 0
    for layout_name, point, pin_node in pins:
        wire_node = place(layout_name, point)
        if wire_node:
            graph.connect(
                pin_node,
                wire_node,
                "pin_attachment",
                "geometric_interpretation",
                graph.nodes[pin_node]["sources"],
                details={"tolerance_drawing_units": tolerance},
            )
            attached[pin_node] = wire_node
        else:
            unattached += 1
    for layout_name, point, wire_number, source in labels:
        wire_node = place(layout_name, point)
        if wire_node:
            graph.nodes[wire_node].setdefault("wire_labels", []).append(
                {"number": wire_number, "source": source}
            )
    if unattached:
        diagnostics.append(
            issue(
                "unattached_connection_points",
                "Some documented pins do not touch selected wire geometry",
                [drawing],
                count=unattached,
            )
        )
    return signals, {
        "drawing": drawing["relative_path"],
        "wire_layers": sorted(layers),
        "basis": layer_basis,
        "unsupported_wire_layer_patterns": unsupported_patterns,
        "segments": len(segments),
        "unattached_pins": unattached,
    }


def add_signal_links(graph: ConnectionGraph, signals: list, diagnostics: list):
    by_code = collections.defaultdict(list)
    for signal in signals:
        by_code[signal["code"].casefold()].append(signal)
    for code, rows in by_code.items():
        sources = [r for r in rows if r["role"] == "source"]
        destinations = [r for r in rows if r["role"] == "destination"]
        if len(sources) != 1 or not destinations or any(r["role"] == "unknown" for r in rows):
            diagnostics.append(
                issue(
                    "ambiguous_signal" if len(sources) > 1 else "incomplete_signal",
                    "Signal code needs exactly one identified source and identified destinations",
                    [r["source"] for r in rows],
                    signal_code=code,
                    sources_count=len(sources),
                    destinations_count=len(destinations),
                )
            )
            continue
        for destination in destinations:
            graph.connect(
                sources[0]["node"],
                destination["node"],
                "signal_continuation",
                "attribute_assertion",
                [sources[0]["source"], destination["source"]],
                wire_numbers=[sources[0].get("wire_number"), destination.get("wire_number")],
            )


def annotate_wire_numbers(graph: ConnectionGraph, diagnostics: list | None = None):
    adjacency = collections.defaultdict(list)
    for edge in graph.edges.values():
        if edge["kind"] in {"wire_segment", "pin_attachment"}:
            adjacency[edge["from_node"]].append((edge["to_node"], edge))
            adjacency[edge["to_node"]].append((edge["from_node"], edge))
    seen = set()
    for start in list(adjacency):
        if start in seen:
            continue
        stack, labels, edges = [start], [], {}
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            labels.extend(graph.nodes[node].get("wire_labels", []))
            for other, edge in adjacency[node]:
                edges[edge["id"]] = edge
                stack.append(other)
        numbers = sorted({label["number"] for label in labels})
        if len(numbers) > 1 and diagnostics is not None:
            diagnostics.append(
                issue(
                    "conflicting_wire_numbers",
                    "Inferred continuous geometry carries multiple wire labels",
                    [label["source"] for label in labels[:16]],
                    wire_numbers=numbers,
                    source_count=len(labels),
                    sources_truncated=len(labels) > 16,
                )
            )
        for edge in edges.values():
            edge["wire_numbers"] = numbers
            edge["details"]["wire_label_sources"] = [label["source"] for label in labels[:16]]
            edge["details"]["wire_label_source_count"] = len(labels)
            edge["details"]["wire_label_sources_truncated"] = len(labels) > 16


def trace_graph(
    snapshot: dict,
    device_id: str,
    terminal: str | None = None,
    domain="electrical",
    max_depth=40,
    max_paths=100,
) -> dict:
    if domain not in {"electrical", "network"} or not 1 <= max_depth <= 100 or not 1 <= max_paths <= 200:
        raise ValueError("Invalid trace domain or budget")
    nodes = snapshot["nodes"]
    starts = [
        identifier
        for identifier, node in nodes.items()
        if node.get("device_id") == device_id
        and (
            terminal is None or str(node.get("terminal")) == terminal or node.get("terminal_code") == terminal
        )
    ]
    if not starts:
        return {"status": "incomplete", "paths": [], "reason": "No matching documented connection point"}
    adjacency = collections.defaultdict(list)
    for edge in snapshot["connections"]:
        if domain in edge["domains"]:
            adjacency[edge["from_node"]].append((edge["to_node"], edge))
            adjacency[edge["to_node"]].append((edge["from_node"], edge))
    device_roles = {d["id"]: d["role"] for d in snapshot.get("devices", [])}
    queue = collections.deque((start, [], {start}) for start in starts)
    paths, incomplete, truncated, visited = [], [], False, 0
    while queue:
        current, edges, seen = queue.popleft()
        visited += 1
        if visited > 10000 or len(paths) >= max_paths:
            truncated = True
            break
        node = nodes[current]
        next_hops = [(other, edge) for other, edge in adjacency[current] if other not in seen]
        passthrough = device_roles.get(node.get("device_id")) in {"terminal", "panel_terminal"} and bool(
            next_hops
        )
        if node.get("device_id") and node["device_id"] != device_id and not passthrough:
            bases = sorted({edge["relationship_basis"] for edge in edges})
            paths.append(
                {
                    "destination": node,
                    "connection_ids": [edge["id"] for edge in edges],
                    "relationship_bases": bases,
                    "status": "reported" if bases == ["native_report"] else "interpreted",
                    "wire_numbers": sorted({n for e in edges for n in e["wire_numbers"]}),
                }
            )
            continue
        if not next_hops and (not node.get("device_id") or not edges):
            incomplete.append(
                {
                    "end_node": current,
                    "connection_ids": [edge["id"] for edge in edges],
                    "reason": "Open documented path without a destination device"
                    if edges
                    else "No selected connection edges at this documented terminal",
                }
            )
        if len(edges) >= max_depth:
            truncated |= bool(next_hops)
            continue
        for other, edge in next_hops:
            if len(queue) >= 10000:
                truncated = True
                break
            queue.append((other, edges + [edge], seen | {other}))
    unique = {(p["destination"]["device_id"], p["destination"].get("terminal")) for p in paths}
    return {
        "status": "incomplete"
        if not paths or truncated or incomplete
        else "branching"
        if len(unique) > 1
        else "documented_path",
        "paths": paths,
        "truncated": truncated,
        "visited_nodes": visited,
        "incomplete_paths": incomplete[:max_paths],
        "scope": "Documented report/attribute relationships and labelled geometry interpretation; no continuity test",
    }
