import json
from pathlib import Path

import ezdxf
import pymupdf

from .extract import convert


def run_tables(source: str, destination: str, options: str):
    opts = json.loads(options)
    with pymupdf.open(source) as pdf:
        found = pdf[opts["page"] - 1].find_tables()
        rows = [
            {
                "page": opts["page"],
                "bbox": list(table.bbox),
                "row_count": table.row_count,
                "column_count": table.col_count,
                "cells": table.extract(),
            }
            for table in found.tables
        ]
    Path(destination).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def run_worker(source: str, destination: str, options: str):
    path, opts = Path(source), json.loads(options)
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            page = doc[opts["page"] - 1]
            scale = opts["width"] / page.rect.width
            if page.rect.height * scale > 12000:
                raise ValueError("Preview exceeds raster height budget")
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            pixmap.save(destination)
    else:
        from ezdxf.addons.drawing import Frontend, RenderContext, layout
        from ezdxf.addons.drawing import pymupdf as backend
        from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration

        dxf, _ = convert(path, opts.get("oda_executable"))
        doc = ezdxf.readfile(dxf)
        target_layout = doc.layouts.get(opts["layout"])
        renderer = backend.PyMuPdfBackend()
        config = Configuration(color_policy=ColorPolicy.BLACK, background_policy=BackgroundPolicy.WHITE)
        Frontend(RenderContext(doc), renderer, config=config).draw_layout(target_layout, finalize=True)
        # Explicit physical page width gives a predictable pixel budget.
        settings = layout.Settings(output_coordinate_space=opts["width"])
        image = renderer.get_pixmap_bytes(
            layout.Page(200, 200), fmt="png", dpi=round(opts["width"] / 200 * 25.4), settings=settings
        )
        Path(destination).write_bytes(image)
