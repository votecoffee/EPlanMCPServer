from __future__ import annotations

import collections
import json
import math
import os
import subprocess
from pathlib import Path

import ezdxf
import pymupdf


def clean(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)) or hasattr(value, "x"):
        return [clean(v) for v in value]
    return str(value)


def convert(source: Path, executable: str | None) -> tuple[Path, dict]:
    if source.suffix.lower() == ".dxf":
        return source, {"engine": "ezdxf", "conversion": None}
    if not executable:
        raise ValueError("DWG/DWT/DWS requires an installed ODA File Converter configured by the operator")
    output = source.parent / "converted"
    output.mkdir()
    # Only the isolated source copy is visible to the converter; audit and recursion are disabled.
    args = [executable, str(source.parent), str(output), "ACAD2018", "DXF", "0", "0", source.name]
    opts = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(args, check=False, capture_output=True, timeout=60, **opts)
    candidates = list(output.glob("*.dxf")) + list(output.glob("*.DXF"))
    candidates = list(dict.fromkeys(candidates))
    if result.returncode or len(candidates) != 1:
        raise ValueError(f"ODA conversion failed: exit={result.returncode}, DXF outputs={len(candidates)}")
    return candidates[0], {
        "engine": "ODA File Converter + ezdxf",
        "conversion": "isolated copy to ACAD2018 DXF",
        "oda_executable": executable,
        "audit": False,
    }


def entity_row(entity, layout: str, block: str | None = None) -> dict:
    kind = entity.dxftype()
    row = {
        "handle": entity.dxf.get("handle"),
        "type": kind,
        "layer": entity.dxf.get("layer", "0"),
        "layout": layout,
        "block_definition": block,
        "properties": clean(entity.dxf.all_existing_dxf_attribs()),
    }
    if kind in {"TEXT", "ATTRIB", "ATTDEF"}:
        row["text"] = entity.dxf.get("text", "")
    elif kind in {"MTEXT", "MLEADER", "MULTILEADER"}:
        try:
            row["text"] = entity.plain_text() if kind == "MTEXT" else entity.get_mtext_content()
        except (AttributeError, ValueError):
            row["text_status"] = "content not available through this entity API"
    if kind == "INSERT":
        row["attributes"] = [
            {
                "handle": a.dxf.handle,
                "tag": a.dxf.tag,
                "text": a.dxf.text,
                "insert": clean(a.dxf.get("insert")),
                "invisible": a.is_invisible,
            }
            for a in entity.attribs
        ]
    if kind == "LWPOLYLINE":
        row["vertices"] = clean(list(entity.get_points()))
        row["closed"] = entity.closed
    if kind == "POLYLINE":
        row["vertices"] = [clean(vertex.dxf.all_existing_dxf_attribs()) for vertex in entity.vertices]
        row["closed"] = entity.is_closed
    if kind == "SPLINE":
        row["control_points"] = clean(list(entity.control_points))
        row["fit_points"] = clean(list(entity.fit_points))
        row["knots"] = clean(list(entity.knots))
        row["weights"] = clean(list(entity.weights))
    if entity.xdata:
        row["xdata"] = {
            name: [{"code": tag.code, "value": clean(tag.value)} for tag in tags]
            for name, tags in entity.xdata.data.items()
        }
    if kind == "DIMENSION":
        try:
            row["measurement"] = clean(entity.get_measurement())
        except (AttributeError, ValueError, TypeError, ezdxf.DXFError):
            row["measurement"] = None
        row["text_override"] = entity.dxf.get("text", "<>")
        row["dimension_type"] = entity.dxf.get("dimtype", 0) & 15
    if kind == "ACAD_TABLE":
        row["table_status"] = "native table cells are not decoded; inspect text entities or PDF tables"
    return row


def extract_cad(source: Path, options: dict) -> dict:
    dxf, backend = convert(source, options.get("oda_executable"))
    doc = ezdxf.readfile(dxf)
    rows, blocks, references = [], [], []
    for layout in doc.layouts:
        for entity in layout:
            rows.append(entity_row(entity, layout.name))
            if len(rows) > options["max_entities"]:
                raise ValueError(
                    "Entity limit exceeded; extraction stopped without publishing a partial cache"
                )
    for block in doc.blocks:
        if block.name.startswith("*Model_Space") or block.name.startswith("*Paper_Space"):
            continue
        record = block.block
        flags = record.dxf.get("flags", 0)
        blocks.append(
            {
                "name": block.name,
                "handle": block.block_record_handle,
                "base_point": clean(record.dxf.get("base_point")),
                "flags": flags,
                "entity_count": len(block),
                "xref_path": record.dxf.get("xref_path", ""),
            }
        )
        if flags & 12:
            references.append(
                {
                    "type": "xref",
                    "block": block.name,
                    "path": record.dxf.get("xref_path", ""),
                    "resolution": "not loaded",
                }
            )
        for entity in block:
            rows.append(entity_row(entity, "@block", block.name))
            if len(rows) > options["max_entities"]:
                raise ValueError("Entity limit exceeded")
    for entity in doc.objects:
        if entity.dxftype() in {"IMAGEDEF", "PDFDEFINITION", "DWFDEFINITION", "DGNDEFINITION"}:
            references.append(
                {
                    "type": entity.dxftype(),
                    "handle": entity.dxf.handle,
                    "path": entity.dxf.get("filename", ""),
                    "resolution": "not loaded",
                }
            )
    layers = [
        {
            "name": layer.dxf.name,
            "handle": layer.dxf.handle,
            "color": layer.dxf.color,
            "linetype": layer.dxf.linetype,
            "off": layer.is_off(),
            "frozen": layer.is_frozen(),
            "locked": layer.is_locked(),
        }
        for layer in doc.layers
    ]
    warnings = [
        "Geometry is structural DXF data; no native AutoCAD validation or 3D solid analysis.",
        "Block definitions use local coordinates. INSERT transforms and arrays are reported, not flattened.",
        "External references, underlays, fonts and links are never loaded automatically.",
        "Dimension measurements are drawing-unit values; angular values use the entity API convention.",
        "Hatch loops, ACIS solids, dynamic block rules and custom dictionaries are not semantically decoded.",
    ]
    if any("PROXY" in row["type"] or row["type"] == "ACAD_TABLE" for row in rows):
        warnings.append(
            "Proxy objects or native tables are present; their semantic content may be incomplete."
        )
    text = []
    for row in rows:
        location = {key: row[key] for key in ("handle", "type", "layer", "layout", "block_definition")}
        if row.get("text"):
            text.append({**location, "text": row["text"], "position": row["properties"].get("insert")})
        for attr in row.get("attributes", []):
            text.append(
                {
                    **location,
                    "handle": attr["handle"],
                    "type": "ATTRIB",
                    "tag": attr["tag"],
                    "text": attr["text"],
                    "position": attr["insert"],
                    "parent_handle": row["handle"],
                }
            )
    return {
        "format": "cad",
        "backend": {**backend, "ezdxf_version": ezdxf.__version__},
        "metadata": {
            "dxf_version": doc.dxfversion,
            "units_code": doc.units,
            "header": {
                key: clean(doc.header.get(key))
                for key in (
                    "$INSUNITS",
                    "$MEASUREMENT",
                    "$LUNITS",
                    "$LUPREC",
                    "$EXTMIN",
                    "$EXTMAX",
                    "$DWGCODEPAGE",
                    "$TITLE",
                    "$AUTHOR",
                    "$LASTSAVEDBY",
                )
            },
        },
        "layouts": [{"name": layout.name, "entity_count": len(layout)} for layout in doc.layouts],
        "entities": rows,
        "text": text,
        "layers": layers,
        "blocks": blocks,
        "references": references,
        "counts": dict(collections.Counter(row["type"] for row in rows)),
        "warnings": warnings,
    }


def extract_pdf(source: Path, options: dict) -> dict:
    rows, pages = [], []
    with pymupdf.open(source) as doc:
        if doc.needs_pass:
            raise ValueError(
                "Encrypted PDF requires an unlocked source copy; no password is accepted by tools"
            )
        if doc.page_count > options["max_pages"]:
            raise ValueError("PDF exceeds configured page limit")
        metadata = clean(doc.metadata)
        for page in doc:
            page_text = []
            for block in page.get_text(
                "dict", sort=True, flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
            )["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(span["text"] for span in line["spans"])
                    if text.strip():
                        row = {
                            "page": page.number + 1,
                            "text": text,
                            "bbox": clean(line["bbox"]),
                            "direction": clean(line["dir"]),
                            "type": "PDF_TEXT",
                        }
                        rows.append(row)
                        page_text.append(text)
                        if len(rows) > options["max_entities"]:
                            raise ValueError("PDF text record limit exceeded")
            pages.append(
                {
                    "page": page.number + 1,
                    "width_points": page.rect.width,
                    "height_points": page.rect.height,
                    "rotation": page.rotation,
                    "text_records": len(page_text),
                    "image_count": len(page.get_images()),
                    "ocr_candidate": not bool(page_text),
                    "coordinate_system": "points, top-left origin, unrotated page",
                }
            )
    return {
        "format": "pdf",
        "backend": {"engine": "PyMuPDF", "version": pymupdf.VersionBind},
        "metadata": metadata,
        "pages": pages,
        "text": rows,
        "entities": [],
        "layers": [],
        "blocks": [],
        "references": [],
        "counts": {"PDF_TEXT": len(rows), "pages": len(pages)},
        "warnings": [
            "PDF text and positions are extracted; drawing units and CAD topology are not inferred.",
            "Image-only pages are flagged for OCR. OCR is not silently substituted for embedded text.",
            "PDF text can include hidden text, font mapping errors or overlapping labels; inspect previews.",
        ],
    }


def run_worker(source: str, destination: str, options: str):
    path = Path(source)
    opts = json.loads(options)
    result = extract_pdf(path, opts) if path.suffix.lower() == ".pdf" else extract_cad(path, opts)
    Path(destination).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
