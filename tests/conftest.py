import json

import ezdxf
import pymupdf
import pytest

from eplan_mcp.config import Config
from eplan_mcp.exports import ExportService
from eplan_mcp.service import DrawingService


@pytest.fixture
def drawing_service(tmp_path):
    source = tmp_path / "drawings"
    source.mkdir()
    doc = ezdxf.new("R2018")
    doc.units = 4
    doc.layers.new("LABELS", dxfattribs={"color": 3})
    model = doc.modelspace()
    model.add_text("PRESS OP101", dxfattribs={"layer": "LABELS", "insert": (5, 7)})
    model.add_mtext("PART\\PABC-123")
    model.add_line((0, 0), (10, 0))
    model.add_lwpolyline([(0, 0), (10, 0), (10, 10)], close=True)
    block = doc.blocks.new("TITLEBLOCK")
    block.add_attdef("DRAWING_NO", (0, 0), text="DEFAULT")
    insert = model.add_blockref("TITLEBLOCK", (20, 30))
    insert.add_auto_attribs({"DRAWING_NO": "Q123456"})
    dimension = model.add_linear_dim(base=(0, 3), p1=(0, 0), p2=(10, 0), angle=0)
    dimension.render()
    doc.saveas(source / "sample.dxf")
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=400)
    page.insert_text((40, 40), "PRESS OP101 - BOM")
    for x in (40, 140, 240):
        page.draw_line((x, 80), (x, 160))
    for y in (80, 120, 160):
        page.draw_line((40, y), (240, y))
    for text, point in (("PART", (50, 100)), ("QTY", (150, 100)), ("ABC-123", (50, 140)), ("2", (150, 140))):
        page.insert_text(point, text)
    pdf.new_page(width=200, height=200)  # no embedded text, must be flagged
    pdf.save(source / "sample.pdf")
    pdf.close()
    (source / "other.step").write_text("ISO-10303-21;", encoding="utf-8")
    (source / "corrupt.dxf").write_text("This is not a DXF", encoding="utf-8")
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"roots": {"test": str(source)}, "state_dir": str(tmp_path / "state")}), encoding="utf-8"
    )
    return DrawingService(Config.load(config_file)), source


@pytest.fixture
def exports(drawing_service):
    drawings, root = drawing_service
    (root / "devices.csv").write_text(
        "DT,Text\n=AP+ST1-K1,Contactor\n=AP+ST1-X1,Terminal\n", encoding="utf-8"
    )
    (root / "connections.csv").write_text(
        "source_tag,source_terminal,target_tag,target_terminal,wire\n"
        "=AP+ST1-X1,1,=AP+ST1-K1,A1,W1\n"
        "=AP+ST1-K1,A2,=AP+ST1-X1,2,W2\n",
        encoding="utf-8",
    )
    (root / "io.xml").write_text(
        "<Report><Point><DT>A1</DT><Address>I0.0</Address></Point></Report>", encoding="utf-8"
    )
    declarations = [
        {
            "relative_path": "devices.csv",
            "kind": "devices",
            "field_map": {"tag": "DT", "description": "Text"},
        },
        {"relative_path": "connections.csv", "kind": "connections"},
        {
            "relative_path": "io.xml",
            "kind": "plc_io",
            "row_tag": "Point",
            "field_map": {"tag": "DT", "address": "Address"},
        },
    ]
    return ExportService(drawings), root, declarations
