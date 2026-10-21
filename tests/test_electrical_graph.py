from eplan_mcp.electrical_graph import (
    ConnectionGraph,
    add_associations,
    add_drawing_geometry,
    add_signal_links,
    select_wire_layers,
    trace_graph,
)
from eplan_mcp.electrical_model import aliases, drawing_metadata, normalize_instance, physical_entities


def device(identifier, role="schematic", **attrs):
    return {"id": identifier, "tag": identifier, "role": role, "sources": [], "attributes": attrs}


def test_nonconductive_associations_never_trace():
    graph, diagnostics = ConnectionGraph(), []
    parent = device("K1")
    child = {**device("child", "child"), "tag": "K1"}
    a, b = device("T1", "terminal", LINKTERM="L"), device("T2", "terminal", LINKTERM="L")
    add_associations(graph, [parent, child, a, b], diagnostics)
    assert len(graph.edges) == 2
    assert all(e["domains"] == [] for e in graph.edges.values())
    assert trace_graph(graph.snapshot(), "K1")["status"] == "incomplete"


def test_trace_through_same_terminal_but_not_between_levels():
    graph = ConnectionGraph()
    devices = [device("PLC"), device("TB", "terminal"), device("PE")]
    a, t, b = [graph.endpoint(d, "1") for d in devices]
    graph.connect(a, t, "reported_from_to", "native_report", [], wire_numbers=["100"])
    graph.connect(t, b, "reported_from_to", "native_report", [], wire_numbers=["100"])
    result = trace_graph({**graph.snapshot(), "devices": devices}, "PLC")
    assert result["status"] == "documented_path"
    assert result["paths"][0]["destination"]["device_id"] == "PE"
    assert result["paths"][0]["status"] == "reported"
    assert result["paths"][0]["wire_numbers"] == ["100"]
    other_level = graph.endpoint(devices[1], "2")
    assert other_level != t
    assert all(other_level not in (e["from_node"], e["to_node"]) for e in graph.edges.values())


def test_domain_bounds_deadends_and_cycles():
    graph = ConnectionGraph()
    a, b = graph.endpoint(device("A")), graph.endpoint(device("B"))
    graph.connect(a, b, "network_connection", "attribute_assertion", [], domains=["network"])
    assert trace_graph(graph.snapshot(), "A")["paths"] == []
    assert trace_graph(graph.snapshot(), "A", domain="network")["paths"]
    m = graph.marker({}, kind="junction")
    graph.connect(a, m, "wire_segment", "geometric_interpretation", [])
    assert trace_graph(graph.snapshot(), "A")["incomplete_paths"]
    c = graph.marker({"name": "c"})
    graph.connect(m, c, "wire_segment", "geometric_interpretation", [])
    graph.connect(c, a, "wire_segment", "geometric_interpretation", [])
    assert trace_graph(graph.snapshot(), "A", max_depth=1)["truncated"]


def geometry(lines, dot=False):
    rows = [
        {
            "handle": str(i),
            "layout": "Model",
            "layer": "WIRE",
            "type": "LINE",
            "properties": {"start": a, "end": b},
        }
        for i, (a, b) in enumerate(lines, 1)
    ]
    for i, point in enumerate([lines[0][0], lines[-1][1]], 100):
        rows.append(
            {
                "handle": str(i),
                "type": "INSERT",
                "layout": "Model",
                "layer": "WIRE",
                "properties": {"name": "SENSOR", "insert": point},
                "attributes": [
                    {"tag": "TAG1", "text": f"PE{i}", "insert": point},
                    {"tag": "X1TERM01", "text": "", "insert": point},
                    {"tag": "TERM01", "text": "1", "insert": point},
                ],
            }
        )
    if dot:
        rows.append(
            {
                "handle": "200",
                "type": "INSERT",
                "layout": "Model",
                "layer": "WIRE",
                "properties": {"name": "WDDOT", "insert": [0, 0, 0]},
                "attributes": [],
            }
        )
    doc = {
        "source": {"root_id": "test", "relative_path": "a.dxf", "sha256": "a" * 64},
        "entities": rows,
        "layers": [{"name": "WIRE"}],
        "blocks": [],
    }
    physical = list(physical_entities(doc, []))
    devices = [
        d
        for row in physical
        if row["type"] == "INSERT"
        if (d := normalize_instance(row, drawing_metadata(doc), aliases()))
    ]
    graph, diagnostics = ConnectionGraph(), []
    add_drawing_geometry(graph, doc, drawing_metadata(doc), physical, devices, diagnostics, [], 0.0001)
    return graph, devices, diagnostics


def test_t_junction_and_crossings_require_documented_join():
    graph, devices, _ = geometry([([-5, 0, 0], [5, 0, 0]), ([0, -5, 0], [0, 5, 0])])
    assert not trace_graph(graph.snapshot(), devices[0]["id"])["paths"]
    graph, devices, _ = geometry([([-5, 0, 0], [5, 0, 0]), ([0, -5, 0], [0, 5, 0])], dot=True)
    assert trace_graph(graph.snapshot(), devices[0]["id"])["paths"]
    graph, devices, _ = geometry([([-5, 0, 0], [5, 0, 0]), ([0, 0, 0], [0, 5, 0])])
    assert trace_graph(graph.snapshot(), devices[0]["id"])["paths"]


def test_duplicate_signal_sources_do_not_connect():
    graph, diagnostics = ConnectionGraph(), []
    signals = [
        {"node": graph.marker({"i": i}), "code": "S1", "role": role, "source": {"i": i}}
        for i, role in enumerate(["source", "source", "destination"])
    ]
    add_signal_links(graph, signals, diagnostics)
    assert not graph.edges and diagnostics[0]["code"] == "ambiguous_signal"


def test_native_wire_layer_wildcards_include_color_and_size_layers():
    doc = {
        "layers": [{"name": name} for name in ("BLU 18AWG", "BLU_16 AWG", "WHT-BLU 16AWG", "BORDER", "WIRES")]
    }
    physical = [
        {
            "type": "INSERT",
            "properties": {"name": "WD_M"},
            "attributes": [{"tag": "WIRELAYS", "text": "BLU*,WHT*,WIRES"}],
        }
    ]
    layers, basis, unsupported = select_wire_layers(doc, physical, [])
    assert layers == {"blu 18awg", "blu_16 awg", "wht-blu 16awg", "wires"}
    assert basis.startswith("WD_M") and unsupported == []
    physical[0]["attributes"][0]["text"] = "~BORDER"
    assert select_wire_layers(doc, physical, [])[2] == ["~border"]
