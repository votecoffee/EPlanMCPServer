import json

import pytest

from eplan_mcp.device_information import DeviceInformation, collect_evidence
from eplan_mcp.exports import ExportService


@pytest.fixture
def device_project(drawing_service):
    drawings, root = drawing_service
    records = {
        "devices": [
            {"tag": "D1", "name": "Camera 1", "description": "Inspection camera"},
            {"tag": "PS1", "description": "Control power supply"},
            {"tag": "AIR1", "description": "Compressed air service"},
        ],
        "network": [
            {"tag": "D1", "ip_address": "192.0.2.20", "interface": "Ethernet", "port": "1"},
            {"tag": "", "ip_address": "198.51.100.3"},
        ],
        "plc_io": [
            {"tag": "D1", "controller": "PLC1", "address": "I0.0", "channel": "0", "signal": "Ready"},
            {"tag": "D1", "controller": "PLC1", "address": "Q0.1", "channel": "1", "signal": "Trigger"},
        ],
        "supplies": [
            {"tag": "PS1", "terminal": "+", "medium": "electrical", "voltage": "24", "voltage_unit": "VDC"},
            {
                "tag": "AIR1",
                "terminal": "OUT",
                "medium": "pneumatic",
                "pressure": "5.5",
                "pressure_unit": "bar",
            },
        ],
        "supply_links": [
            {
                "source_tag": "PS1",
                "source_terminal": "+",
                "target_tag": "FU1",
                "target_terminal": "IN",
                "medium": "electrical",
            },
            {
                "source_tag": "FU1",
                "source_terminal": "OUT",
                "target_tag": "XT1",
                "target_terminal": "1",
                "medium": "electrical",
            },
            {
                "source_tag": "XT1",
                "source_terminal": "2",
                "target_tag": "D1",
                "target_terminal": "PWR",
                "medium": "electrical",
            },
            {
                "source_tag": "AIR1",
                "source_terminal": "OUT",
                "target_tag": "D1",
                "target_terminal": "AIR",
                "medium": "pneumatic",
            },
        ],
        "bridges": [
            {
                "source_tag": "FU1",
                "source_terminal": "IN",
                "target_tag": "FU1",
                "target_terminal": "OUT",
                "medium": "electrical",
                "flow_direction": "source_to_target",
            },
            {
                "source_tag": "XT1",
                "source_terminal": "1",
                "target_tag": "XT1",
                "target_terminal": "2",
                "medium": "electrical",
                "flow_direction": "bidirectional",
            },
        ],
    }

    def build():
        reports = []
        for kind, rows in records.items():
            if rows:
                path = root / (kind + ".json")
                columns = set().union(*(row.keys() for row in rows))
                rectangular = [{column: row.get(column, "") for column in columns} for row in rows]
                path.write_text(json.dumps(rectangular), encoding="utf-8")
                reports.append({"relative_path": path.name, "kind": kind})
        return ExportService(drawings).import_reports("test", reports)["snapshot_id"]

    return DeviceInformation(drawings), records, build


def test_device_profile_combines_reported_facts_and_both_feed_domains(device_project):
    service, _, build = device_project
    identifier = build()
    profile = service.profile(identifier, "D1")
    assert profile["status"] == "reported_device"
    assert profile["facts"]["description"][0]["value"] == "Inspection camera"
    assert profile["facts"]["ip_address"][0]["value"] == "192.0.2.20"
    assert profile["facts"]["ip_address"][0]["valid_ip_literal"]
    assert {v["value"] for v in profile["facts"]["address"]} == {"I0.0", "Q0.1"}
    assert not any(r["field"] == "address" for r in profile["conflicts"])
    assert profile["supplies"]["electrical"]["supplies"][0]["fields"]["tag"] == "PS1"
    assert profile["supplies"]["pneumatic"]["supplies"][0]["fields"]["pressure"] == "5.5"
    assert all(p["complete_for_supplied_relationships"] for p in profile["supplies"].values())
    power = service.supply(identifier, "D1", "electrical", terminal="PWR")
    assert power["paths"][0]["endpoint"][0] == "PS1"
    assert len(power["paths"][0]["edges"]) == 5
    assert all(e["source"]["sha256"] and e["source"]["row"] for e in power["paths"][0]["edges"])


def test_supply_trace_requires_explicit_bridges_and_direction(device_project):
    service, records, build = device_project
    records["bridges"].pop(0)
    traced = service.supply(build(), "D1", terminal="PWR")
    assert traced["status"] == "incomplete"
    assert traced["paths"][0]["status"] == "unresolved_upstream"
    assert traced["paths"][0]["endpoint"][:2] == ("FU1", "OUT")
    records["connections"] = [
        records["supply_links"].pop(0)
    ]  # Ordinary endpoint order supplies no flow direction.
    traced = service.supply(build(), "D1", terminal="PWR")
    assert traced["diagnostics"]["items"][0]["code"] == "unusable_supply_relationship"


def test_scope_ambiguity_prevents_merged_profiles_and_unscoped_paths(device_project):
    service, records, build = device_project
    records["devices"] = [{"tag": "D1", "installation": "A"}, {"tag": "D1", "installation": "B"}]
    identifier = build()
    profile = service.profile(identifier, "D1")
    assert profile["status"] == "ambiguous_scope" and profile["facts"] == {}
    traced = service.supply(identifier, "D1", terminal="PWR")
    assert traced["paths"][0]["status"] == "ambiguous_scope"


def test_branching_cycles_depth_limits_and_missing_ports_stay_explicit(device_project):
    service, records, build = device_project
    shallow = service.supply(build(), "D1", terminal="PWR", max_depth=2)
    assert shallow["truncated"] and shallow["paths"][0]["status"] == "depth_limit"
    records["supplies"][0].pop("terminal")
    identifier = build()
    traced = service.supply(identifier, "D1", terminal="PWR")
    assert traced["paths"][0]["status"] == "supply_port_unresolved"
    assert not traced["complete_for_supplied_relationships"]
    assert service.supply(identifier, "missing")["status"] == "unresolved_start"


def test_conflicting_ip_claims_are_retained_with_port_context(device_project):
    service, records, build = device_project
    records["network"].append({"tag": "D1", "ip_address": "192.0.2.21", "interface": "Ethernet", "port": "1"})
    profile = service.profile(build(), "D1")
    assert profile["fact_counts"]["ip_address"] == 2
    assert profile["conflicts"][0]["field"] == "ip_address"
    assert profile["conflicts"][0]["review_required"]


def test_multiple_supplies_and_cycles_are_not_collapsed(device_project):
    service, records, build = device_project
    records["supplies"].append({"tag": "PS2", "terminal": "+", "medium": "electrical", "voltage": "24"})
    records["supply_links"].append(
        {
            "source_tag": "PS2",
            "source_terminal": "+",
            "target_tag": "D1",
            "target_terminal": "PWR",
            "medium": "electrical",
        }
    )
    traced = service.supply(build(), "D1", terminal="PWR")
    assert {s["fields"]["tag"] for p in traced["paths"] for s in p["supplies"]} == {"PS1", "PS2"}
    records["supply_links"].append(
        {
            "source_tag": "D1",
            "source_terminal": "PWR",
            "target_tag": "FU1",
            "target_terminal": "IN",
            "medium": "electrical",
        }
    )
    traced = service.supply(build(), "D1", terminal="PWR")
    assert any(p["status"] == "cycle" for p in traced["paths"])
    assert not traced["complete_for_supplied_relationships"]


@pytest.mark.anyio
async def test_device_tools_through_real_stdio(device_project):
    import sys

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    service, _, build = device_project
    identifier = build()
    drawings = service.drawings
    drawings.load("test", "sample.pdf")
    source = drawings.config.roots["test"]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "eplan_mcp", "--config", str(source.parent / "config.json"), "serve"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=60.0) as client:
            await client.initialize()
            profile = await client.call_tool(
                "eplan_get_device_profile", {"snapshot_id": identifier, "tag": "D1"}
            )
            assert not profile.is_error, profile.content
            assert profile.structured_content["facts"]["name"][0]["value"] == "Camera 1"
            traced = await client.call_tool(
                "eplan_trace_device_supply",
                {"snapshot_id": identifier, "tag": "D1", "medium": "pneumatic", "terminal": "AIR"},
            )
            assert (
                not traced.is_error
                and traced.structured_content["paths"][0]["supplies"][0]["fields"]["tag"] == "AIR1"
            )
            evidence = await client.call_tool(
                "eplan_collect_device_evidence",
                {
                    "root_id": "test",
                    "drawing_paths": ["sample.pdf"],
                    "device_query": "PRESS OP101",
                    "category": "device",
                },
            )
            assert not evidence.is_error and evidence.structured_content["items"]


def test_pdf_candidate_context_does_not_establish_membership(drawing_service):
    drawings, root = drawing_service
    import pymupdf

    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((40, 40), "D1 inspection camera")
    page.insert_text((40, 60), "IP 192.0.2.20")
    page.insert_text((40, 80), "24VDC POWER SUPPLY")
    page.insert_text((40, 100), "AIR SUPPLY 5.5 bar")
    page.insert_text((40, 120), "I0.0 Ready")
    page.insert_text((40, 400), "192.0.2.99")
    pdf.new_page().insert_text((40, 40), "192.0.2.88")
    pdf.save(root / "device.pdf")
    pdf.close()
    drawings.load("test", "device.pdf")
    evidence = collect_evidence(drawings, "test", ["device.pdf"], "D1", radius=100)
    assert set(evidence["candidate_counts"]) == {"device", "ip", "power", "air", "io"}
    assert {r["value"] for r in evidence["items"] if r["category"] == "ip"} == {"192.0.2.20"}
    assert all(not r["establishes_device_identity_or_supply"] for r in evidence["items"])
    assert all(r["source"]["sha256"] and r["location"]["page"] == 1 for r in evidence["items"])
    missing = collect_evidence(drawings, "test", ["not-there.pdf"])
    assert missing["coverage"][0]["status"] == "unavailable"


def test_historical_snapshot_without_supply_collections_remains_readable(exports):
    import hashlib

    from eplan_mcp.exports import atomic_json, canonical

    service, _, declarations = exports
    identifier = service.import_reports("test", declarations)["snapshot_id"]
    body = service.load(identifier)
    for kind in ("supplies", "supply_links", "supply_references", "bridges"):
        body["records"].pop(kind)
    legacy = "ep_" + hashlib.sha256(canonical(body).encode()).hexdigest()
    atomic_json(service.folder / "snapshots" / (legacy + ".json"), body)
    assert service.query(legacy, "supplies")["total"] == 0
    assert service.compare(legacy, legacy)["total"] == 0
    assert DeviceInformation(service.drawings).profile(legacy, "=AP+ST1-K1")["status"] == "reported_device"


def test_feed_references_are_visible_without_creating_paths_or_device_ratings(device_project):
    service, records, build = device_project
    records["supply_links"] = [r for r in records["supply_links"] if r["medium"] != "pneumatic"]
    records["supply_references"] = [
        {
            "tag": "D1",
            "medium": "pneumatic",
            "source_reference": "Air manifold on A1",
            "target_reference": "Camera purge on A2",
            "description": "Regulator design note only",
            "pressure": "6",
            "pressure_unit": "bar",
        }
    ]
    identifier = build()
    traced = service.supply(identifier, "D1", "pneumatic")
    assert traced["status"] == "unresolved_start" and not traced["paths"]
    assert not traced["complete_for_supplied_relationships"]
    assert traced["reported_references"]["total"] == 1
    reference = traced["reported_references"]["items"][0]
    assert reference["fields"]["source_reference"] == "Air manifold on A1"
    assert not reference["establishes_terminal_connectivity"]
    profile = service.profile(identifier, "D1")
    assert profile["supplies"]["pneumatic"]["reported_references"]["total"] == 1
    assert "pressure" not in profile["facts"]
    assert profile["facts"]["description"][0]["value"] == "Inspection camera"
    assert service.supply(identifier, "D1")["reported_references"]["total"] == 0
    assert service.supply(identifier, "other", "pneumatic")["reported_references"]["total"] == 0


def test_feed_reference_scopes_and_pagination_remain_explicit(device_project):
    service, records, build = device_project
    records["devices"] = [{"tag": "D1", "location": "A"}, {"tag": "D1", "location": "B"}]
    records["supply_references"] = [
        {"tag": "D1", "medium": "pneumatic", "location": location, "source_reference": f"Supply {i}"}
        for location in ("A", "B")
        for i in range(12)
    ]
    identifier = build()
    assert service.profile(identifier, "D1")["status"] == "ambiguous_scope"
    profile = service.profile(identifier, "D1", location="A")
    references = profile["supplies"]["pneumatic"]["reported_references"]
    assert references["total"] == 12 and len(references["items"]) == 10
    assert references["next_offset"] == 10
    assert all(r["fields"]["location"] == "A" for r in references["items"])
    rows = service.exports.query(identifier, "supply_references", offset=10, limit=10)
    assert len(rows["items"]) == 10


def test_bracketed_io_literals_retain_scope_and_reject_partial_addresses(drawing_service):
    import pymupdf

    drawings, root = drawing_service
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), "MANIFOLD A DO[101] DI[102] AI[3] AO[4] GI[5] GO[6] UI[7] UO[8]")
        page.insert_text((40, 70), "%IX1.2 QW4 I2.0")
        page.insert_text((40, 100), "XDO[101] DO[102]suffix DO[bad] DO[1.2] DO[3 I2.0suffix I3.2.1")
        pdf.new_page().insert_text((40, 40), "MANIFOLD B DO[101]")
        pdf.save(root / "io.pdf")
    drawings.load("test", "io.pdf")
    evidence = collect_evidence(drawings, "test", ["io.pdf"], category="io")
    assert evidence["total"] == 12
    assert {r["value"] for r in evidence["items"]} == {
        "DO[101]",
        "DI[102]",
        "AI[3]",
        "AO[4]",
        "GI[5]",
        "GO[6]",
        "UI[7]",
        "UO[8]",
        "%IX1.2",
        "QW4",
        "I2.0",
    }
    repeated = [r for r in evidence["items"] if r["value"] == "DO[101]"]
    assert {r["location"]["page"] for r in repeated} == {1, 2}
    assert all(not r["establishes_device_identity_or_supply"] for r in repeated)
    scoped = collect_evidence(drawings, "test", ["io.pdf"], "MANIFOLD A", "io", radius=10)
    assert all(r["location"]["page"] == 1 for r in scoped["items"])


def test_air_feed_labels_are_candidates_without_implied_connections(drawing_service):
    import pymupdf

    drawings, root = drawing_service
    labels = ["PLANT AIR", '1/2" AIR FEED', "AIR PREP UNIT", "AIR MANIFOLD", "DUMP VALVE", "AIR LOCKOUT"]
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        for i, label in enumerate(labels):
            page.insert_text((40, 40 + i * 20), label)
        page.insert_text((40, 200), "AIR FEEDBACK REPAIR MANIFOLD")
        pdf.save(root / "air.pdf")
    drawings.load("test", "air.pdf")
    evidence = collect_evidence(drawings, "test", ["air.pdf"], category="air")
    assert evidence["total"] == len(labels)
    assert {r["value"] for r in evidence["items"]} == {
        "PLANT AIR",
        "AIR FEED",
        "AIR PREP UNIT",
        "AIR MANIFOLD",
        "DUMP VALVE",
        "AIR LOCKOUT",
    }
    assert all(r["source"]["sha256"] and r["location"]["bbox"] for r in evidence["items"])
    assert all(not r["establishes_device_identity_or_supply"] for r in evidence["items"])
