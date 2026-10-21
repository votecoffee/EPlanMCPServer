import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from eplan_mcp.exports import parse_report
from eplan_mcp.service import sha256


def test_import_provenance_preservation_freshness_and_readback(exports):
    service, root, declarations = exports
    before = {p.name: sha256(p) for p in root.iterdir() if p.is_file()}
    result = service.import_reports("test", declarations)
    identifier = result["snapshot_id"]
    assert result["counts"]["devices"] == 2
    assert result["counts"]["plc_io"] == 1
    row = service.query(identifier, "devices", "Contactor")["items"][0]
    assert row["source"]["row"] == 2 and row["source"]["sha256"] == before["devices.csv"]
    assert row["raw"]["DT"] == "=AP+ST1-K1"
    assert row["native_engine_validated"] is False
    exported = service.export(identifier)
    assert exported["sha256"] == sha256(service.folder / "exports" / (identifier + ".json"))
    assert {p.name: sha256(p) for p in root.iterdir() if p.is_file()} == before
    (root / "devices.csv").write_text("DT,Text\nK2,Replacement\n", encoding="utf-8")
    assert service.get(identifier)["sources"][0]["state"] == "changed"
    assert service.query(identifier, "devices")["total"] == 2
    (root / "devices.csv").unlink()
    assert service.get(identifier)["sources"][0]["state"] == "unavailable"


def test_no_implicit_device_terminal_bridge(exports):
    service, _, declarations = exports
    identifier = service.import_reports("test", declarations)["snapshot_id"]
    trace = service.trace(identifier, "=AP+ST1-X1", "1")
    assert len(trace["items"]) == 1  # A1 must not bridge internally to A2.
    assert trace["items"][0]["fields"]["wire"] == "W1"
    assert service.trace(identifier, "missing")["status"] == "unresolved_start"
    assert service.compare(identifier, identifier)["total"] == 0


def test_compare_retains_duplicate_multiplicity_and_checks(exports):
    service, root, declarations = exports
    before = service.import_reports("test", declarations)["snapshot_id"]
    with (root / "devices.csv").open("a", encoding="utf-8") as stream:
        stream.write("=AP+ST1-K1,Contactor\n")
    after = service.import_reports("test", declarations)["snapshot_id"]
    changes = service.compare(before, after)["items"]
    assert len(changes) == 1 and changes[0]["count"] == 1 and changes[0]["change"] == "added"
    assert service.checks(after)["items"][0]["code"] == "potential_duplicate"


@pytest.mark.parametrize(
    "data,suffix,options",
    [
        (b"DT,DT\nK1,K2", ".csv", {}),
        (b"DT,Text\nK1", ".csv", {}),
        (b"DT\nK1,unexpected", ".csv", {}),
        (b"[]", ".json", {}),
        (b'[{"tag": {"nested": "value"}}]', ".json", {}),
        (b"<R><Row><DT>K1</DT></Row></R>", ".xml", {}),
        (b"<R><Row><DT>K1</DT><DT>K2</DT></Row></R>", ".xml", {"row_tag": "Row"}),
        (
            b'<!DOCTYPE R [<!ENTITY x SYSTEM "file:///secret">]><R><Row>&x;</Row></R>',
            ".xml",
            {"row_tag": "Row"},
        ),
        (b"native project bytes", ".zw1", {}),
    ],
)
def test_malformed_or_unsupported_reports_rejected(data, suffix, options):
    with pytest.raises((ValueError, TypeError)):
        parse_report(data, suffix, **options)


def test_namespace_utf16_and_explicit_property_ids():
    data = '<R xmlns="urn:example"><Row P20010="K1"><P20011>Text</P20011></Row></R>'.encode("utf-16")
    rows = parse_report(data, ".xml", row_tag="{urn:example}Row")
    assert rows[0][1] == {"P20010": "K1", "{urn:example}P20011": "Text"}


def test_path_escape_mapping_error_and_snapshot_integrity(exports):
    service, _, declarations = exports
    for path in ("../config.json", "C:/Windows/win.ini", "../../secret.xml"):
        with pytest.raises(ValueError):
            service.import_reports("test", [{"relative_path": path, "kind": "devices"}])
    with pytest.raises(ValueError, match="Mapped columns"):
        service.import_reports(
            "test", [{"relative_path": "devices.csv", "kind": "devices", "field_map": {"tag": "missing"}}]
        )
    identifier = service.import_reports("test", declarations)["snapshot_id"]
    path = service.folder / "snapshots" / (identifier + ".json")
    body = json.loads(path.read_bytes())
    body["records"]["devices"][0]["fields"]["tag"] = "tampered"
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        service.load(identifier)
    with pytest.raises(ValueError, match="Invalid snapshot"):
        service.load("../../secret")


def test_concurrent_identical_imports_are_content_addressed(exports):
    service, _, declarations = exports
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.import_reports("test", declarations), range(2)))
    assert results[0]["snapshot_id"] == results[1]["snapshot_id"]
    assert len(list((service.folder / "snapshots").glob("*.json"))) == 1


def test_scoped_tag_ambiguity_stops_trace(exports):
    service, root, declarations = exports
    (root / "scoped.csv").write_text("tag,installation,location\nK1,A,L1\nK1,B,L2\n", encoding="utf-8")
    (root / "connections.csv").write_text(
        "source_tag,source_terminal,target_tag,target_terminal\nK1,1,X1,1\n", encoding="utf-8"
    )
    declarations[0] = {"relative_path": "scoped.csv", "kind": "devices"}
    identifier = service.import_reports("test", declarations)["snapshot_id"]
    trace = service.trace(identifier, "K1", "1")
    assert trace["status"] == "ambiguous_start" and trace["items"] == []
