"""Independent read-only local data access, always against an isolated source copy."""

from __future__ import annotations

import base64
import datetime
import decimal
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

from .config import inside
from .service import paginate, sha256
from .worker_launch import worker_command

XML_LIMIT = 16 * 1024 * 1024
BINARY_WINDOW = 4 * 1024 * 1024
INFLATED_LIMIT = 16 * 1024 * 1024
LOCAL_FORMATS = {".xml", ".epj", ".mdb", ".accdb", ".elk", ".ell", ".eod", ".eox", ".slk", ".xlk"}


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in {low}..{high}")


def xml_document(data):
    if len(data) > XML_LIMIT:
        raise ValueError("XML exceeds 16 MiB")
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    text = data.decode(encoding)
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper() or "\x00" in text:
        raise ValueError("DTD, entity declarations and null bytes are not allowed")
    root = ET.fromstring(text)
    stack, count = [(root, 0)], 0
    while stack:
        element, depth = stack.pop()
        count += 1
        if depth > 64 or count > 100_000:
            raise ValueError("XML exceeds depth/node budget")
        stack.extend((c, depth + 1) for c in element)
    return root


def xml_value(element):
    return {
        "tag": element.tag,
        "attributes": dict(element.attrib),
        "text": element.text or "",
        "tail": element.tail or "",
        "children": [xml_value(c) for c in element],
    }


def read_xml(path, options):
    root = xml_document(path.read_bytes())
    tags = {}
    for element in root.iter():
        tags[element.tag] = tags.get(element.tag, 0) + 1
    tag = options.get("record_tag")
    if tag is None:
        page = paginate(
            [{"tag": k, "count": v} for k, v in sorted(tags.items())], options["offset"], options["limit"]
        )
        return {
            "root_tag": root.tag,
            "root_attributes": dict(root.attrib),
            "tags": page["items"],
            "tag_total": page["total"],
            "offset": page["offset"],
            "next_offset": page["next_offset"],
            "interpretation": "XML structure only; property semantics are not inferred",
        }
    if not isinstance(tag, str) or not tag or len(tag) > 256:
        raise ValueError("Supply an exact XML record_tag (Clark notation for namespaces)")
    rows = []
    query = options.get("query")
    for ordinal, element in enumerate(root.iter(tag), 1):
        value = xml_value(element)
        if query and query.casefold() not in json.dumps(value, ensure_ascii=False).casefold():
            continue
        rows.append(
            {
                "record_ordinal": ordinal,
                "record_tag": tag,
                "value": value,
                "evidence": "parsed_xml_record",
                "native_engine_validated": False,
            }
        )
    return {"root_tag": root.tag, **paginate(rows, options["offset"], options["limit"])}


def project_link(data):
    if len(data) > 65536:
        raise ValueError("Project link exceeds 64 KiB; no binary fallback decoding")
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    text = data.decode(encoding)
    if "\x00" in text:
        raise ValueError("Project link contains null bytes")
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    references = [s for s in lines if s.casefold().endswith(".edb")]
    versions = [s for s in lines if re.fullmatch(r"\d+(?:\.\d+){1,3}", s)]
    return {
        "encoding": encoding,
        "lines": lines,
        "database_reference": references[0] if len(references) == 1 else None,
        "version_text": versions[0] if len(versions) == 1 else None,
        "interpretation": "project link text; no native database semantics or project opening",
    }


def inflate_at(data, offset):
    integer(offset, "stream_offset", 0, max(0, len(data) - 1))
    decoder = zlib.decompressobj()
    output = bytearray()
    position = offset
    while position < len(data) and not decoder.eof:
        end = min(position + 65536, len(data))
        output.extend(decoder.decompress(memoryview(data)[position:end], INFLATED_LIMIT + 1 - len(output)))
        position = end
        if len(output) > INFLATED_LIMIT:
            raise ValueError("Compressed stream exceeds 16 MiB output budget")
    if not decoder.eof:
        raise ValueError("Compressed stream is invalid or incomplete")
    consumed = position - offset - len(decoder.unused_data)
    output = bytes(output)
    return output, {
        "stream_offset": offset,
        "compressed_bytes": consumed,
        "inflated_bytes": len(output),
        "inflated_sha256": hashlib.sha256(output).hexdigest(),
        "checksum_verified": True,
    }


def text_candidates(data, minimum=4):
    # Byte-exact candidates, not inferred device tags or electrical relationships.
    patterns = [
        ("ascii", rb"[\x20-\x7e]{%d,}" % minimum),
        ("utf-16-le", rb"(?:[\x20-\x7e]\x00){%d,}" % minimum),
        ("utf-16-be", rb"(?:\x00[\x20-\x7e]){%d,}" % minimum),
    ]
    rows = []
    for encoding, pattern in patterns:
        for match in re.finditer(pattern, data):
            # Bound records without losing the remainder: each segment keeps its own offset.
            step = 8000 if encoding == "ascii" else 16000
            for start in range(match.start(), match.end(), step):
                raw = data[start : min(start + step, match.end())]
                rows.append(
                    {
                        "byte_offset": start,
                        "byte_length": len(raw),
                        "encoding": encoding,
                        "text": raw.decode(encoding),
                        "evidence": "binary_text_candidate",
                    }
                )
            if len(rows) > 100_000:
                raise ValueError("Too many text candidates; select a smaller byte window")
    return sorted(rows, key=lambda r: (r["byte_offset"], r["encoding"]))


def read_binary(path, options):
    data = path.read_bytes()
    stream = None
    if options.get("stream_offset") is not None:
        data, stream = inflate_at(data, options["stream_offset"])
    start, length = options.get("byte_offset", 0), options.get("byte_length", 65536)
    integer(start, "byte_offset", 0, len(data))
    integer(length, "byte_length", 1, BINARY_WINDOW)
    window = data[start : start + length]
    end = start + len(window)
    result = {
        "data_bytes": len(data),
        "byte_offset": start,
        "byte_length": len(window),
        "next_byte_offset": end if end < len(data) else None,
        "stream": stream,
        "coordinate_system": "inflated bytes" if stream else "source file bytes",
        "limitations": [
            "Text candidates may include incidental binary matches.",
            "Record identities, properties, geometry and connectivity are not inferred.",
            "ASCII-compatible text only; other character encodings require explicit byte inspection.",
        ],
    }
    if options["operation"] == "bytes":
        integer(length, "byte_length", 1, 4096)
        return {**result, "hex": window.hex()}
    rows = text_candidates(window, options.get("minimum_length", 4))
    for row in rows:
        row["byte_offset"] += start
    query = options.get("query")
    if query:
        rows = [r for r in rows if query.casefold() in r["text"].casefold()]
    return {**result, **paginate(rows, options["offset"], options["limit"])}


def compressed_streams(path, options):
    data = path.read_bytes()
    start, length = options.get("byte_offset", 0), options.get("byte_length", BINARY_WINDOW)
    integer(start, "byte_offset", 0, len(data))
    integer(length, "byte_length", 1, BINARY_WINDOW)
    # Include one look-ahead byte so a zlib header at the final window byte is not lost.
    window = data[start : start + length + 1]
    rows, attempts, budget_hit, decoded_bytes = [], 0, False, 0
    covered_until = -1
    for match in re.finditer(rb"\x78[\x01\x5e\x9c\xda]", window):
        if match.start() >= length:
            continue
        position = start + match.start()
        if position < covered_until:
            continue
        attempts += 1
        if attempts > 512 or decoded_bytes >= 32 * 1024 * 1024:
            budget_hit = True
            break
        try:
            output, info = inflate_at(data, position)
        except (ValueError, zlib.error):
            continue
        decoded_bytes += len(output)
        covered_until = position + info["compressed_bytes"]
        rows.append(info)
    end = min(start + length, len(data))
    return {
        "scan_byte_offset": start,
        "scan_byte_length": end - start,
        "attempts": min(attempts, 512),
        "scan_budget_hit": budget_hit,
        "next_scan_byte_offset": position if budget_hit else end if end < len(data) else None,
        "scope": "checksum-valid non-overlapping zlib streams whose headers start within the selected window; not native records",
        **paginate(rows, options["offset"], options["limit"]),
    }


def eod_slots(path, options):
    """Experimental byte-slot partitioning from a repeated header pattern; no object lifecycle claims."""
    data = path.read_bytes()
    if len(data) < 24 or data[6:8] != b"\x00\x13" or data[12:14] != b"\x00\x13":
        raise ValueError("EOD header pattern is unsupported; use byte/text readers")
    signature = data[4:18]
    size = options.get("slot_size")
    if size is None:
        positions, position = [], 4
        while len(positions) < 100_001:
            position = data.find(signature, position)
            if position < 0:
                break
            positions.append(position - 4)
            position += 1
        if len(positions) < 3 or len(positions) > 100_000:
            raise ValueError(
                "Insufficient bounded header evidence to infer slots; provide an explicit slot_size or use byte/text readers"
            )
        size = math.gcd(*(b - a for a, b in zip(positions, positions[1:])))
    integer(size, "slot_size", 24, 1_048_576)
    if len(data) % size or len(data) // size > 100_000:
        raise ValueError("Slot geometry does not exactly partition the file within the slot budget")
    total = len(data) // size
    rows = []
    for index in range(options["offset"], min(total, options["offset"] + options["limit"])):
        start = index * size
        block = data[start : start + size]
        matches = block[4:18] == signature
        texts = text_candidates(block)
        for row in texts:
            row["byte_offset"] += start
        rows.append(
            {
                "slot_index": index,
                "byte_offset": start,
                "byte_length": size,
                "matches_header_pattern": matches,
                "header_u32be_at_0": int.from_bytes(block[:4], "big"),
                "header_u16be_at_4": int.from_bytes(block[4:6], "big"),
                "text_candidates": texts[:20],
                "text_candidates_truncated": len(texts) > 20,
                "evidence": "experimental_byte_slot",
            }
        )
    end = options["offset"] + len(rows)
    return {
        "slot_size": size,
        "geometry": "explicit" if options.get("slot_size") else "inferred_from_repeated_header_intervals",
        "header_signature": signature.hex(),
        "total": total,
        "offset": options["offset"],
        "next_offset": end if end < total else None,
        "items": rows,
        "limitations": [
            "Header integers are raw values; semantic object IDs/types have not been authenticated.",
            "A matching header does not prove an active object; unmatched slots are not classified as deleted.",
            "No property, geometry, page hierarchy or electrical relationship is inferred.",
        ],
    }


def scalar(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {
            "type": "binary",
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "base64": base64.b64encode(raw[:4096]).decode(),
            "truncated": len(raw) > 4096,
        }
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    return str(value)


def access_data(path, options):
    if os.name != "nt":
        raise ValueError("Access reading currently requires Windows and the installed ACE OLE DB provider")
    import winreg

    import pythoncom
    import win32com.client

    # MCP stdio deliberately inherits a small environment. ADO schema components use
    # expandable COM registrations referencing CommonProgramFiles. Recover only this
    # OS-owned folder from machine configuration, never caller-supplied tool arguments.
    if not os.environ.get("CommonProgramFiles"):
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion") as key:
            common = winreg.QueryValueEx(key, "CommonFilesDir")[0]
        os.environ["CommonProgramFiles"] = common

    pythoncom.CoInitialize()
    connection = None
    try:
        connection = win32com.client.Dispatch("ADODB.Connection")
        connection.Mode = 1  # adModeRead, set before Open.
        connection.ConnectionTimeout = 10
        connection.CommandTimeout = 30
        # Path is an app-generated isolated copy; no caller-controlled connection string or SQL.
        connection.Open(
            f'Provider=Microsoft.ACE.OLEDB.12.0;Data Source="{path}";Mode=Read;Persist Security Info=False;'
        )
        catalog = win32com.client.Dispatch("ADOX.Catalog")
        catalog.ActiveConnection = connection
        schema = connection.OpenSchema(20)  # adSchemaTables
        tables = []
        while not schema.EOF:
            name, kind = str(schema.Fields("TABLE_NAME").Value), str(schema.Fields("TABLE_TYPE").Value)
            if kind == "TABLE" and not name.casefold().startswith("msys"):
                metadata = catalog.Tables(name)
                properties = {p.Name: p.Value for p in metadata.Properties}
                if (
                    not any(
                        properties.get(p)
                        for p in (
                            "Jet OLEDB:Link Provider String",
                            "Jet OLEDB:Link Datasource",
                            "Jet OLEDB:Create Link",
                        )
                    )
                    and metadata.Type == "TABLE"
                ):
                    tables.append(name)
                metadata = None
            if len(tables) > 1000:
                raise ValueError("Database table count exceeds 1000")
            schema.MoveNext()
        schema.Close()
        schema = catalog = None
        if options.get("table") is None:
            if options.get("column") is not None:
                raise ValueError("Select a table before requesting a cell")
            return {
                "backend": "Windows ACE OLE DB",
                "read_only": True,
                **paginate([{"table": name} for name in sorted(tables)], options["offset"], options["limit"]),
            }
        table = options["table"]
        if table not in tables or any(c in table for c in "[]\r\n\x00"):
            raise ValueError("Select an exact local base-table name returned by the table inventory")
        recordset = win32com.client.Dispatch("ADODB.Recordset")
        recordset.Open(f"SELECT * FROM [{table}]", connection, 0, 1)  # forward-only, adLockReadOnly
        columns = [
            {"name": recordset.Fields(i).Name, "ado_type": recordset.Fields(i).Type}
            for i in range(recordset.Fields.Count)
        ]
        if len(columns) > 1000:
            raise ValueError("Database table exceeds column budget")
        ordinal, rows = 0, []
        column = options.get("column")
        if column is not None and column not in {c["name"] for c in columns}:
            raise ValueError("Unknown exact column name")
        while not recordset.EOF:
            if ordinal >= options["offset"]:
                if column is not None:
                    value = recordset.Fields(column).Value
                    start, length = options.get("start", 0), options.get("length", 8000)
                    integer(start, "start", 0, 1_000_000_000)
                    integer(length, "length", 1, 16000)
                    binary = isinstance(value, (bytes, bytearray, memoryview))
                    content = bytes(value) if binary else "" if value is None else str(value)
                    chunk = content[start : start + length]
                    recordset.Close()
                    return {
                        "table": table,
                        "column": column,
                        "row_ordinal": ordinal + 1,
                        "content_kind": "binary" if binary else "text",
                        "null": value is None,
                        "start": start,
                        "total_length": len(content),
                        "next_start": start + len(chunk) if start + len(chunk) < len(content) else None,
                        "base64" if binary else "text": base64.b64encode(chunk).decode() if binary else chunk,
                        "row_order": "provider order within this source hash; no primary key inferred",
                    }
                if len(rows) >= options["limit"]:
                    break
                rows.append(
                    {
                        "row_ordinal": ordinal + 1,
                        "fields": {
                            c["name"]: scalar(recordset.Fields(i).Value) for i, c in enumerate(columns)
                        },
                    }
                )
            ordinal += 1
            recordset.MoveNext()
        has_more = not recordset.EOF
        recordset.Close()
        if column is not None:
            raise ValueError("Row offset is beyond the end of the table")
        page = paginate(rows, 0, options["limit"])
        consumed = options["offset"] + len(page["items"])
        return {
            "backend": "Windows ACE OLE DB",
            "read_only": True,
            "table": table,
            "columns": columns,
            "items": page["items"],
            "offset": options["offset"],
            "next_offset": consumed if has_more or len(page["items"]) < len(rows) else None,
            "total": None,
            "row_order": "provider order within this source hash; no primary key inferred",
        }
    finally:
        if connection is not None and connection.State:
            connection.Close()
        pythoncom.CoUninitialize()


def run_worker(source, destination, options):
    opts = json.loads(options)
    path = Path(source)
    operation = opts["operation"]
    if operation == "archive":
        result = archive_data(path, opts)
    elif operation == "xml":
        result = read_xml(path, opts)
    elif operation == "link":
        result = project_link(path.read_bytes())
    elif operation == "streams":
        result = compressed_streams(path, opts)
    elif operation == "slots":
        result = eod_slots(path, opts)
    elif operation in {"bytes", "text"}:
        result = read_binary(path, opts)
    elif operation == "access":
        result = access_data(path, opts)
    else:
        raise ValueError("Unknown local data operation")
    Path(destination).write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def archive_data(path, options):
    """Access ordinary ZIP members without trusting member paths or native backup extensions."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 100_000:
            raise ValueError("ZIP member count exceeds budget")
        member = options.get("member")
        if member is None:
            return {
                "format": "zip",
                "extracted": False,
                **paginate(
                    [
                        {
                            "name": item.filename,
                            "bytes": item.file_size,
                            "compressed_bytes": item.compress_size,
                            "crc32": f"{item.CRC:08x}",
                            "encrypted": bool(item.flag_bits & 1),
                            "directory": item.is_dir(),
                        }
                        for item in entries
                    ],
                    options["offset"],
                    options["limit"],
                ),
            }
        matches = [i for i in entries if i.filename == member]
        if len(matches) != 1:
            raise ValueError("Choose one unique exact ZIP member name")
        entry = matches[0]
        normalized = member.replace("\\", "/")
        if (
            normalized.startswith("/")
            or ":" in normalized
            or ".." in normalized.split("/")
            or entry.is_dir()
            or (entry.external_attr >> 16) & 0o170000 == 0o120000
            or entry.flag_bits & 1
            or entry.file_size > 64 * 1024 * 1024
        ):
            raise ValueError("Unsafe, encrypted, linked or oversized ZIP member")
        operation = options.get("member_operation", "text")
        suffix = Path(normalized).suffix.lower()
        allowed = {
            "xml": {".xml", ".epj"},
            "access": {".mdb", ".accdb"},
            "link": {".elk", ".ell"},
            "text": LOCAL_FORMATS | {".pdf"},
            "bytes": LOCAL_FORMATS,
            "streams": LOCAL_FORMATS,
        }
        if operation not in allowed or suffix not in allowed[operation]:
            raise ValueError("Unsupported ZIP member operation/format")
        with archive.open(entry) as stream:
            data = stream.read(64 * 1024 * 1024 + 1)
        if len(data) != entry.file_size or len(data) > 64 * 1024 * 1024:
            raise ValueError("ZIP member size exceeds budget or declaration")
        with tempfile.TemporaryDirectory(dir=path.parent) as folder:
            source, destination = Path(folder) / ("member" + suffix), Path(folder) / "result.json"
            source.write_bytes(data)
            if suffix == ".pdf" and operation == "text":
                from .extract import extract_pdf

                document = extract_pdf(source, {"max_pages": 2000, "max_entities": 500_000})
                rows = document["text"]
                if options.get("query"):
                    rows = [r for r in rows if options["query"].casefold() in r["text"].casefold()]
                result = {
                    "format": "pdf",
                    "pages": len(document["pages"]),
                    "warnings": document["warnings"],
                    **paginate(rows, options["offset"], options["limit"]),
                }
            else:
                run_worker(str(source), str(destination), json.dumps({**options, "operation": operation}))
                result = json.loads(destination.read_bytes())
        return {
            "archive_member": {
                "name": member,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
                "crc32": f"{entry.CRC:08x}",
            },
            **result,
        }


class LocalDataService:
    def __init__(self, drawings):
        self.drawings, self.config = drawings, drawings.config

    def read(self, root_id, relative_path, operation, **options):
        path = self.config.resolve(root_id, relative_path)
        formats = {
            "archive": {".zip"},
            "slots": {".eod"},
            "xml": {".xml", ".epj"},
            "link": {".elk", ".ell"},
            "access": {".mdb", ".accdb"},
            "streams": LOCAL_FORMATS,
            "bytes": LOCAL_FORMATS,
            "text": LOCAL_FORMATS,
        }
        if operation not in formats or path.suffix.lower() not in formats[operation]:
            raise ValueError("Unsupported local file format/operation")
        offset, limit = options.setdefault("offset", 0), options.setdefault("limit", 50)
        integer(offset, "offset", 0, 1_000_000)
        integer(limit, "limit", 1, 200)
        if options.get("query") is not None and (
            not isinstance(options["query"], str) or len(options["query"]) > 500
        ):
            raise ValueError("query must be a literal string up to 500 characters")
        if "minimum_length" in options:
            integer(options["minimum_length"], "minimum_length", 4, 128)
        if operation == "xml" and path.stat().st_size > XML_LIMIT:
            raise ValueError("XML exceeds 16 MiB")
        before = sha256(path)
        with tempfile.TemporaryDirectory(dir=self.config.state / "scratch") as folder:
            scratch = Path(folder)
            snapshot = scratch / ("source" + path.suffix.lower())
            shutil.copyfile(path, snapshot)
            if sha256(snapshot) != before or sha256(path) != before:
                raise ValueError("Source changed during isolated copy")
            destination = scratch / "result.json"
            arguments = worker_command(
                "_local", str(snapshot), str(destination), json.dumps({**options, "operation": operation})
            )
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            with self.drawings.coordinator.worker():
                try:
                    completed = subprocess.run(
                        arguments,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        timeout=self.config.worker_timeout,
                        **kwargs,
                    )
                except subprocess.TimeoutExpired as error:
                    raise ValueError("Local reader timed out; no partial result returned") from error
            if completed.returncode != 0 or not destination.is_file():
                raise ValueError(
                    "Local reader failed: " + completed.stderr.decode("utf-8", errors="replace")[-2000:]
                )
            result = json.loads(destination.read_bytes())
        if sha256(path) != before:
            raise ValueError("Source changed during read; result discarded")
        return {
            "source": {
                "root_id": root_id,
                "relative_path": relative_path,
                "sha256": before,
                "size_bytes": path.stat().st_size,
            },
            "native_engine_validated": False,
            **result,
        }

    def project(self, root_id, relative_path, offset=0, limit=50):
        result = self.read(root_id, relative_path, "link")
        link = self.config.resolve(root_id, relative_path)
        reference = result["database_reference"]
        if not reference:
            return {**result, "database_state": "unresolved_reference", **paginate([], offset, limit)}
        relative = Path(reference)
        if relative.is_absolute() or relative.drive or ":" in reference or ".." in relative.parts:
            raise ValueError("Project link target must stay relative to its source folder")
        folder = (link.parent / relative).resolve()
        if not inside(folder, self.config.roots[root_id]) or folder.is_symlink():
            raise ValueError("Project database target is outside the configured root")
        if not folder.is_dir():
            return {**result, "database_state": "missing_folder", **paginate([], offset, limit)}
        rows = []
        for path in sorted(folder.iterdir()):
            if (
                path.is_file()
                and not path.is_symlink()
                and inside(path.resolve(), self.config.roots[root_id])
            ):
                rows.append(
                    {
                        "relative_path": path.relative_to(self.config.roots[root_id]).as_posix(),
                        "extension": path.suffix.lower(),
                        "size_bytes": path.stat().st_size,
                        "access": "binary_evidence"
                        if path.suffix.lower() in {".eod", ".eox"}
                        else "inventory",
                    }
                )
        if sha256(link) != result["source"]["sha256"]:
            raise ValueError("Project link changed during inventory")
        return {
            **result,
            "database_state": "local_folder",
            "database_contents_are_atomic": False,
            **paginate(rows, offset, limit),
        }
