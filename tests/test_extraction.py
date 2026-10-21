import json
import shutil

import ezdxf
import pytest

from eplan_mcp.config import Config
from eplan_mcp.server import create_server
from eplan_mcp.service import paginate, sha256


def test_eplan_geometry_attributes_and_dimension(drawing_service):
    service, source = drawing_service
    before = sha256(source / "sample.dxf")
    result = service.load("test", "sample.dxf")
    assert result["source"]["sha256"] == before == sha256(source / "sample.dxf")
    assert result["metadata"]["units_code"] == 4
    dimension = next(row for row in result["entities"] if row["type"] == "DIMENSION")
    assert dimension["measurement"] == pytest.approx(10)
    insert = next(row for row in result["entities"] if row["type"] == "INSERT")
    assert insert["attributes"][0]["tag"] == "DRAWING_NO"
    assert insert["attributes"][0]["text"] == "Q123456"
    assert any(
        row["text"] == "Q123456" and row["parent_handle"] == insert["handle"] for row in result["text"]
    )
    assert any(row["text"] == "PART\nABC-123" for row in result["text"])
    line = next(row for row in result["entities"] if row["type"] == "LINE" and row["layout"] == "Model")
    assert line["properties"]["end"] == [10, 0, 0]


def test_pdf_page_coordinates_and_empty_flag(drawing_service):
    service, source = drawing_service
    before = sha256(source / "sample.pdf")
    doc = service.load("test", "sample.pdf")
    row = next(row for row in doc["text"] if "PRESS" in row["text"])
    assert row["page"] == 1 and len(row["bbox"]) == 4
    assert doc["pages"][1]["ocr_candidate"] is True
    assert doc["pages"][0]["ocr_candidate"] is False
    assert sha256(source / "sample.pdf") == before
    assert service.records("test", "sample.pdf", "text", page=2)["total"] == 0


def test_boundaries_and_unsupported_formats(drawing_service, tmp_path):
    service, source = drawing_service
    outside = tmp_path / "outside.pdf"
    shutil.copyfile(source / "sample.pdf", outside)
    for path in ("../outside.pdf", str(outside), "sample.pdf:stream"):
        with pytest.raises(ValueError):
            service.config.resolve("test", path)
    with pytest.raises(ValueError, match="not supported"):
        service.load("test", "other.step")
    with pytest.raises(ValueError, match="Unknown root"):
        service.inventory("unknown")
    bad = tmp_path / "bad-config.json"
    bad.write_text(
        json.dumps({"roots": {"test": str(source)}, "state_dir": str(source / "state")}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="overlap"):
        Config.load(bad)


def test_corrupt_source_fails_without_cache(drawing_service):
    service, _ = drawing_service
    with pytest.raises(ValueError, match="worker failed"):
        service.load("test", "corrupt.dxf")
    assert list((service.config.state / "cache").glob("*.json")) == []


def test_cache_invalidation_and_search_freshness(drawing_service):
    service, source = drawing_service
    before = service.search("test", "PRESS")
    assert before["coverage"]["complete"] is False
    result = service.index("test", limit=5)
    assert [row["status"] for row in result["results"]].count("failed") == 1
    found = service.search("test", "press")
    assert found["total"] >= 2
    assert found["coverage"]["current_indexed_files"] == 2
    assert found["coverage"]["unindexed_files"] == 1
    doc = ezdxf.readfile(source / "sample.dxf")
    doc.modelspace().query("TEXT")[0].dxf.text = "NEW LABEL"
    doc.saveas(source / "sample.dxf")
    after = service.search("test", "PRESS")
    assert after["coverage"]["stale_files"] == 1
    assert all(row["relative_path"] != "sample.dxf" for row in after["items"])
    assert service.records("test", "sample.dxf", "text", query="NEW LABEL")["total"] == 1


def test_paginated_filters_and_explicit_long_text(drawing_service):
    service, _ = drawing_service
    result = service.records("test", "sample.dxf", "entities", entity_type="TEXT", layer="LABELS")
    assert result["total"] == 1
    assert result["items"][0]["text"] == "PRESS OP101"
    records = [{"text": "x" * 20000, "record_index": i} for i in range(30)]
    first = paginate(records, 0, 200)
    assert first["items"][0]["text_truncated"]
    assert first["next_offset"] is not None
    assert len(json.dumps(first).encode()) < 200000
    with pytest.raises(ValueError):
        paginate(records, -1, 10)


def test_compare_text_multiplicity(drawing_service):
    service, source = drawing_service
    doc = ezdxf.readfile(source / "sample.dxf")
    doc.modelspace().add_text("PRESS OP101")
    doc.saveas(source / "revision.dxf")
    diff = service.compare("test", "sample.dxf", "test", "revision.dxf")
    row = next(row for row in diff["items"] if row["value"] == "PRESS OP101")
    assert row["before_count"] == 1 and row["after_count"] == 2


def test_pdf_table_cells_and_render(drawing_service):
    service, source = drawing_service
    before = sha256(source / "sample.pdf")
    tables = service.pdf_tables("test", "sample.pdf", 1)
    assert tables["items"][0]["cells"] == [["PART", "QTY"], ["ABC-123", "2"]]
    preview = service.render("test", "sample.pdf", width=600)
    from PIL import Image

    with Image.open(preview["preview_path"]) as image:
        assert image.size == (600, 400)
    assert sha256(source / "sample.pdf") == before


def test_eplan_preview(drawing_service):
    service, source = drawing_service
    before = sha256(source / "sample.dxf")
    result = service.render("test", "sample.dxf", width=800)
    from PIL import Image

    with Image.open(result["preview_path"]) as image:
        assert 790 <= image.width <= 810
    assert sha256(source / "sample.dxf") == before


@pytest.mark.anyio
async def test_mcp_classification_and_result_budget(drawing_service):
    service, _ = drawing_service
    server = create_server(service)
    tools = await server.list_tools()
    by_name = {tool.name: tool for tool in tools}
    assert len(tools) == 46
    for name, tool in by_name.items():
        assert tool.output_schema is not None
        assert tool.annotations.read_only_hint == (
            name
            not in {
                "eplan_index_project",
                "eplan_render_preview",
                "eplan_build_electrical_project",
                "eplan_export_electrical_project",
                "eplan_import_reports",
                "eplan_export_snapshot",
            }
        )
        assert tool.annotations.open_world_hint is False
    result = await server.call_tool("eplan_status", {})
    assert result
