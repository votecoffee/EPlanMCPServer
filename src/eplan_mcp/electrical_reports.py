"""Readers for explicitly supplied Electrical project/report files; no native engine claims."""

from __future__ import annotations

import csv
import io
import json
import os
import re
from pathlib import Path

from .config import inside

REPORT_KINDS = {"plc_connections", "from_to", "components", "panel", "network", "drawing_map"}
REPORT_ALIASES = {
    "components": {"TAGNAME": "TAG"},
    "panel": {"TAGNAME": "TAG"},
    "from_to": {
        f"{stem}{n}": f"{side}_{target}"
        for n, side in ((1, "FROM"), (2, "TO"))
        for stem, target in (
            ("CMP", "TAG"),
            ("PIN", "TERM"),
            ("INST", "INST"),
            ("LOC", "LOC"),
            ("HDL", "HDL"),
            ("CMPHDL", "HDL"),
            ("DWGIX", "DWGIX"),
            ("SH", "SH"),
            ("PD", "TERMDESC"),
            ("FILENAME", "FILENAME"),
        )
    },
}


def read_text(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def parse_wdp(path: Path, root: Path) -> dict:
    description, properties, drawings, pending = {}, {}, [], {}
    for number, raw in enumerate(read_text(path).splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if match := re.match(r"^([*?+])\[(\d+)\](.*)$", line):
            target = description if match.group(1) == "*" else properties
            target[match.group(1) + match.group(2)] = match.group(3)
        elif line.startswith("=====SUB="):
            pending["project_folder"] = line[len("=====SUB=") :]
        elif line.startswith("====REF"):
            pending["reference_only"] = True
        elif line.startswith("==="):
            pending.setdefault("descriptions", []).append(line[3:])
        elif line.startswith("=="):
            pending["subsection"] = line[2:]
        elif line.startswith("="):
            pending["section"] = line[1:]
        elif line.rstrip('"').lower().endswith((".dwg", ".dxf", ".dwt", ".dws")):
            normalized = line.replace("\\", "/").strip('"')
            # Reject outside-root declarations lexically before any filesystem resolution.
            candidate = Path(os.path.abspath(path.parent / normalized))
            allowed = inside(candidate, root)
            if allowed:
                candidate = candidate.resolve()
                allowed = inside(candidate, root)
            drawings.append(
                {
                    "declared_path": line,
                    "relative_path": candidate.relative_to(root).as_posix() if allowed else None,
                    "exists": candidate.is_file() if allowed else False,
                    "allowed": allowed,
                    "line": number,
                    **pending,
                }
            )
            pending = {}
    return {
        "descriptions": description,
        "properties": properties,
        "drawings": drawings,
        "format": "AutoCAD Electrical WDP",
        "native_relationship": "project_membership_only",
    }


def parse_report(path: Path, kind: str, field_map: dict | None = None) -> list[dict]:
    if kind not in REPORT_KINDS:
        raise ValueError("Unknown Electrical report kind")
    if field_map is not None and (
        not isinstance(field_map, dict)
        or any(
            not isinstance(k, str) or not isinstance(v, str) or not k.strip() or not v.strip()
            for k, v in field_map.items()
        )
    ):
        raise ValueError("field_map must map nonempty original headers to canonical field names")
    if path.suffix.lower() not in {".csv", ".tsv", ".json"}:
        raise ValueError("Report inputs must be CSV, TSV or a JSON array of row objects")
    text = read_text(path)
    if path.suffix.lower() == ".json":
        rows = json.loads(text)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("JSON report must be an array of flat row objects")
    else:
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("Reports need unique nonempty column headers")
        rows = list(reader)
    if len(rows) > 100_000:
        raise ValueError("Report exceeds 100000 rows")
    mapped = []
    for index, row in enumerate(rows, 1 if path.suffix.lower() == ".json" else 2):
        fields = {}
        for name, value in row.items():
            if name is None or isinstance(value, (dict, list)):
                raise ValueError("Malformed report row or nested cell")
            key = (field_map or {}).get(name, name).strip().upper()
            if key in fields:
                raise ValueError("Report mapping creates duplicate normalized column names")
            fields[key] = "" if value is None else str(value).strip()
        if not any(fields.values()):
            continue
        for original, canonical in REPORT_ALIASES.get(kind, {}).items():
            if original in fields:
                if canonical in fields and fields[canonical] != fields[original]:
                    raise ValueError("Conflicting canonical and Electrical report columns")
                fields[canonical] = fields[original]
        requirements = {
            "plc_connections": {"PLCTAG", "PLCADDR"},
            "from_to": {"FROM_TAG", "TO_TAG"},
            "components": {"TAG"},
            "panel": {"TAG"},
            "network": {"TAG"},
            "drawing_map": {"DWGIX", "FILENAME"},
        }
        if not requirements[kind] <= fields.keys():
            raise ValueError(
                f"{kind} report is missing columns: {sorted(requirements[kind] - fields.keys())}"
            )
        mapped.append({"row": index, "fields": fields})
    return mapped
