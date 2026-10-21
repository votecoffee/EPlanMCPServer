import copy
import json

import pymupdf
import pytest

from eplan_mcp.device_information import DeviceInformation
from eplan_mcp.exports import ExportService
from eplan_mcp.service import sha256


@pytest.fixture
def reviewed(drawing_service):
    drawings, root = drawing_service
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        for i, text in enumerate(("PS1 OUT -> D1 PWR", "24VDC", "D1 inspection camera", "192.0.2.20")):
            page.insert_text((40, 40 + i * 20), text)
        pdf.new_page().insert_text((40, 40), "Different page")
        pdf.save(root / "review.pdf")
    drawings.load("test", "review.pdf")
    reference = {
        "root_id": "test",
        "relative_path": "review.pdf",
        "sha256": sha256(root / "review.pdf"),
        "page": 1,
        "quotes": ["PS1 OUT -> D1 PWR", "24VDC", "D1 inspection camera", "192.0.2.20"],
    }
    sidecar = {
        "schema": "eplan-row-evidence/1",
        "rows": [
            {
                "row": 1,
                "reviewer": "Synthetic test reviewer",
                "note": "Named endpoints checked; pins not traced.",
                "references": [reference],
            }
        ],
    }
    rows = {
        "devices": [{"tag": "D1", "description": "Inspection camera"}],
        "network": [{"tag": "D1", "ip_address": "192.0.2.20"}],
        "supplies": [{"tag": "PS1", "terminal": "OUT", "medium": "electrical", "voltage": "24"}],
        "supply_links": [
            {
                "source_tag": "PS1",
                "source_terminal": "OUT",
                "target_tag": "D1",
                "target_terminal": "PWR",
                "medium": "electrical",
            }
        ],
        "supply_references": [
            {
                "tag": "D1",
                "medium": "pneumatic",
                "source_reference": "Air feed on another sheet",
                "target_reference": "Camera purge, ports unresolved",
            }
        ],
    }
    declarations = []
    for kind, values in rows.items():
        (root / f"{kind}.json").write_text(json.dumps(values))
        declarations.append(
            {"relative_path": f"{kind}.json", "kind": kind, "evidence_relative_path": "review.json"}
        )

    def save(body=sidecar):
        (root / "review.json").write_text(json.dumps(body))

    save()
    return ExportService(drawings), root, declarations, sidecar, save


def test_reviewed_rows_retain_original_pdf_in_profiles_traces_and_freshness(reviewed):
    exports, root, declarations, _, _ = reviewed
    before = {p.name: sha256(p) for p in root.iterdir() if p.is_file()}
    imported = exports.import_reports("test", declarations)
    identifier = imported["snapshot_id"]
    assert exports.import_reports("test", declarations)["snapshot_id"] == identifier
    assert len([s for s in imported["sources"] if s["kind"] == "reviewed_drawing_source"]) == 1
    service = DeviceInformation(exports.drawings)
    profile = service.profile(identifier, "D1")
    fact = profile["facts"]["ip_address"][0]
    assert fact["evidence"] == "reviewed_drawing_assertion"
    assert not fact["review"]["reviewer_authenticated"]
    reference = fact["references"][0]
    assert reference["source"]["sha256"] == before["review.pdf"]
    assert reference["quotes"][0]["locations"][0]["bbox"]
    traced = service.supply(identifier, "D1", terminal="PWR")
    assert traced["complete_for_supplied_relationships"]
    assert traced["paths"][0]["edges"][0]["evidence"] == "reviewed_drawing_assertion"
    assert traced["paths"][0]["supplies"][0]["references"]
    assert {p.name: sha256(p) for p in root.iterdir() if p.is_file()} == before
    (root / "review.pdf").write_bytes(b"changed original")
    sources = service.profile(identifier, "D1")["sources"]
    assert next(s for s in sources if s["kind"] == "reviewed_drawing_source")["state"] == "changed"
    assert exports.query(identifier, "network")["items"][0]["references"] == [reference]
    with pytest.raises(ValueError):
        exports.import_reports("test", declarations)
    (root / "review.pdf").unlink()
    sources = exports.get(identifier)["sources"]
    assert next(s for s in sources if s["kind"] == "reviewed_drawing_source")["state"] == "unavailable"


@pytest.mark.parametrize(
    "case",
    [
        "wrong_hash",
        "wrong_page",
        "bool_page",
        "missing_quote",
        "partial_quote",
        "outside_root",
        "extra_row",
        "duplicate_row",
        "missing_row",
        "empty_reviewer",
        "unknown_field",
        "bad_quotes",
    ],
)
def test_reviewed_evidence_rejects_invalid_bindings_without_publishing(reviewed, case):
    exports, _, declarations, sidecar, save = reviewed
    body = copy.deepcopy(sidecar)
    row = body["rows"][0]
    ref = row["references"][0]
    if case == "wrong_hash":
        ref["sha256"] = "0" * 64
    elif case == "wrong_page":
        ref["page"] = 2
    elif case == "bool_page":
        ref["page"] = True
    elif case == "missing_quote":
        ref["quotes"] = ["not in the drawing"]
    elif case == "partial_quote":
        ref["quotes"] = ["PS1"]
    elif case == "outside_root":
        ref["relative_path"] = "../config.json"
    elif case == "extra_row":
        row["row"] = 2
    elif case == "duplicate_row":
        body["rows"].append(copy.deepcopy(row))
    elif case == "missing_row":
        body["rows"] = []
    elif case == "empty_reviewer":
        row["reviewer"] = " "
    elif case == "unknown_field":
        ref["approved"] = True
    elif case == "bad_quotes":
        ref["quotes"] = [123]
    save(body)
    with pytest.raises(ValueError):
        exports.import_reports("test", declarations)
    assert not list((exports.folder / "snapshots").glob("*.json"))


def test_csv_evidence_uses_source_row_numbers_and_tracks_sidecar_freshness(reviewed):
    exports, root, _, body, save = reviewed
    (root / "reviewed.csv").write_text("tag,description\nD1,Camera\n")
    body["rows"][0]["row"] = 2
    save()
    declaration = {
        "kind": "devices",
        "relative_path": "reviewed.csv",
        "evidence_relative_path": "review.json",
    }
    identifier = exports.import_reports("test", [declaration])["snapshot_id"]
    assert exports.query(identifier, "devices")["items"][0]["source"]["row"] == 2
    body["rows"][0]["note"] = "Amended interpretation"
    save()
    changed = exports.import_reports("test", [declaration])["snapshot_id"]
    assert changed != identifier
    assert (
        next(s for s in exports.get(identifier)["sources"] if s["kind"] == "review_evidence")["state"]
        == "changed"
    )


def test_original_changes_before_publication_discards_reviewed_snapshot(reviewed, monkeypatch):
    import eplan_mcp.exports as module

    exports, root, declarations, _, _ = reviewed
    real_hash = module.sha256

    def changed(path):
        if path.name == "review.pdf":
            (root / "review.pdf").write_bytes(b"changed during import")
        return real_hash(path)

    monkeypatch.setattr(module, "sha256", changed)
    with pytest.raises(ValueError, match="changed before snapshot"):
        exports.import_reports("test", declarations)
    assert not list((exports.folder / "snapshots").glob("*.json"))


@pytest.mark.anyio
async def test_reviewed_import_and_original_freshness_through_stdio(reviewed):
    import sys

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    _, root, declarations, _, _ = reviewed
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "eplan_mcp", "--config", str(root.parent / "config.json"), "serve"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=60.0) as client:
            await client.initialize()
            imported = await client.call_tool(
                "eplan_import_reports",
                {
                    "root_id": "test",
                    "reports": declarations,
                    "request_id": "reviewed-import-1",
                },
            )
            assert not imported.is_error, imported.content
            identifier = imported.structured_content["snapshot_id"]
            traced = await client.call_tool(
                "eplan_trace_device_supply",
                {
                    "snapshot_id": identifier,
                    "tag": "D1",
                    "terminal": "PWR",
                },
            )
            assert not traced.is_error, traced.content
            edge = traced.structured_content["paths"][0]["edges"][0]
            assert edge["evidence"] == "reviewed_drawing_assertion" and edge["references"]
            (root / "review.pdf").unlink()
            profile = await client.call_tool(
                "eplan_get_device_profile", {"snapshot_id": identifier, "tag": "D1"}
            )
            assert not profile.is_error, profile.content
            result = profile.structured_content
            assert result["facts"]["ip_address"][0]["references"]
            air = result["supplies"]["pneumatic"]
            assert air["status"] == "unresolved_start"
            reference = air["reported_references"]["items"][0]
            assert reference["evidence"] == "reviewed_drawing_assertion"
            assert reference["references"] and not reference["establishes_terminal_connectivity"]
            assert (
                next(s for s in result["sources"] if s["kind"] == "reviewed_drawing_source")["state"]
                == "unavailable"
            )
