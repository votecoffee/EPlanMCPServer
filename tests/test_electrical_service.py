import json
from pathlib import Path

import ezdxf
import jsonschema
import pytest

from eplan_mcp.config import Config
from eplan_mcp.electrical import ElectricalService
from eplan_mcp.service import DrawingService, sha256


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    doc = ezdxf.new()
    doc.layers.new("WIRE")
    block = doc.blocks.new("DEVICE")
    for key in ("TAG1", "DESC1", "MFG", "CAT", "INST", "LOC", "TERM01", "X1TERM01", "TAGA01", "CHANNEL01"):
        block.add_attdef(key, (0, 0))
    for point, values in [
        ((0, 0), {"TAG1": "PLC1", "TAGA01": "I0.0", "TERM01": "0", "CHANNEL01": "0"}),
        ((10, 0), {"TAG1": "PE1", "DESC1": "Sensor", "MFG": "Example", "CAT": "S1", "TERM01": "1"}),
    ]:
        ref = doc.modelspace().add_blockref("DEVICE", point)
        ref.add_auto_attribs(values)
    doc.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": "WIRE"})
    doc.saveas(root / "a.dxf")
    (root / "project.wdp").write_text("===Control schematic\na.dxf\n", encoding="utf-8")
    drawing_service = DrawingService(Config({"test": root}, tmp_path / "state"))
    drawing_service.load("test", "a.dxf")
    return ElectricalService(drawing_service), root


def test_inventory_tracing_export_and_preservation(project):
    service, root = project
    before = sha256(root / "a.dxf")
    built = service.build("test", electrical_project_path="project.wdp")
    identifier = built["project_id"]
    assert built["drawing_count"] == 1 and built["counts"]["devices"] == 2
    assert built["freshness"]["status"] == "current"
    io = service.plc_io(identifier, trace_connections=True)["items"][0]
    assert io["channel"] == "0" and io["address"] == "I0.0"
    assert len(io["connected_devices"]) == 1
    assert io["trace"]["paths"][0]["status"] == "interpreted"
    exported = service.export(identifier)
    snapshot = json.loads(Path(exported["path"]).read_text(encoding="utf-8"))
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas/electrical-project.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.validate(snapshot, schema)
    assert exported["readback_verified"] and sha256(Path(exported["path"])) == exported["sha256"]
    assert snapshot["devices"][0]["sources"][0]["drawing"]["sha256"] == before
    assert sha256(root / "a.dxf") == before
    assert service.build("test", electrical_project_path="project.wdp")["project_id"] == identifier


def test_revision_comparison_and_stale_snapshot(project):
    service, root = project
    before = service.build("test")["project_id"]
    doc = ezdxf.readfile(root / "a.dxf")
    doc.modelspace().query("INSERT")[1].get_attrib("CAT").dxf.text = "S2"
    doc.saveas(root / "a.dxf")
    assert service.get(before)["freshness"]["status"] == "stale"
    with pytest.raises(ValueError, match="cache is missing"):
        service.build("test")
    service.drawings.load("test", "a.dxf")
    after = service.build("test")["project_id"]
    diff = service.compare(before, after)
    assert diff["total"] == 1 and diff["items"][0]["change"] == "changed"
    assert diff["items"][0]["before"]["fields"]["catalog"] == "S1"
    assert service.compare(after, after)["total"] == 0
    doc = ezdxf.readfile(root / "a.dxf")
    doc.modelspace().query("INSERT")[0].get_attrib("TAGA01").dxf.text = "I0.1"
    doc.saveas(root / "a.dxf")
    service.drawings.load("test", "a.dxf")
    next_revision = service.build("test")["project_id"]
    changes = service.compare(after, next_revision)["items"]
    assert len(changes) == 1 and changes[0]["kind"] == "plc_io"
    assert changes[0]["after"][0]["fields"]["address"] == "I0.1"


def test_native_plc_report_mapping_and_no_order_guess(project):
    service, root = project
    raw = service.drawings.load("test", "a.dxf")
    plc, sensor = [r["handle"] for r in raw["entities"] if r["type"] == "INSERT" and r["layout"] != "@block"]
    (root / "map.csv").write_text("DWGIX,FILENAME\n55,a.dxf\n", encoding="utf-8")
    (root / "io.csv").write_text(
        f"PLCTAG,PLCADDR,PLCTERM,PLCTERMCODE,PLCDWGIX,PLCHDL,CMPTAG,CMPTERM,CMPDWGIX,CMPHDL,PLCWNUM,TERMTAG,TERMTERM\nPLC1,I0.0,0,01,55,{plc},PE1,1,55,{sensor},100,TB1,10\n",
        encoding="utf-8",
    )
    reports = [
        {"kind": "plc_connections", "relative_path": "io.csv"},
        {"kind": "drawing_map", "relative_path": "map.csv"},
    ]
    result = service.build("test", reports=reports)
    snapshot = service.load(result["project_id"])
    assert len(snapshot["devices"]) == 3  # PLC/sensor merge by exact drawing+handle, plus reported terminal.
    native = next(r for r in snapshot["plc_io"] if r["relationship_basis"] == "native_report")
    assert native["channel"] is None and native["terminal_code"] == "01"
    assert native["terminal_strip"]["number"] == "10" and native["connected_devices"]
    assert any(e["native_relationship"] for e in snapshot["connections"])
    assert not any(e["kind"] == "reported_from_to" for e in snapshot["connections"])
    # Without FILETIME mapping the native row remains useful but its source drawing is unresolved.
    unmapped = service.build("test", reports=reports[:1])
    assert unmapped["check_counts"]["native_drawing_reference_unresolved"] >= 1


def test_invalid_scope_and_report_paths(project):
    service, _ = project
    for tolerance in (0, -1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            service.build("test", tolerance=tolerance)
    with pytest.raises(ValueError):
        service.load("../outside")
    with pytest.raises(ValueError):
        service.build("test", reports=[{"kind": "components", "relative_path": "../outside.csv"}])


def test_rebuilding_duplicate_tags_preserves_snapshot(project):
    service, root = project
    doc = ezdxf.readfile(root / "a.dxf")
    doc.modelspace().add_blockref("DEVICE", (20, 0)).add_auto_attribs({"TAG1": "PE1", "DESC1": "Sensor"})
    doc.saveas(root / "a.dxf")
    service.drawings.load("test", "a.dxf")
    first = service.build("test")
    assert first["check_counts"]["duplicate_tag"] == 1
    before = (service.state / "projects" / (first["project_id"] + ".json")).read_bytes()
    second = service.build("test")
    assert second["project_id"] == first["project_id"]
    assert (service.state / "projects" / (first["project_id"] + ".json")).read_bytes() == before


def test_text_address_order_is_stable(project):
    service, root = project
    doc = ezdxf.readfile(root / "a.dxf")
    doc.modelspace().add_text("192.0.2.20 / 255.255.255.0 / 192.0.2.10")
    doc.saveas(root / "a.dxf")
    service.drawings.load("test", "a.dxf")
    snapshot = service.load(service.build("test")["project_id"])
    assert [r["ip_address"] for r in snapshot["network"]] == ["192.0.2.10", "192.0.2.20", "255.255.255.0"]
