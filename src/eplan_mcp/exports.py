"""Source-bound EPLAN report analysis; no native project access or implicit property mapping."""

from __future__ import annotations

import collections
import csv
import hashlib
import io
import json
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from .reviewed_evidence import load_row_evidence
from .service import paginate, sha256

KINDS = {
    "devices",
    "connections",
    "plc_io",
    "terminals",
    "cables",
    "parts",
    "network",
    "pages",
    "supplies",
    "supply_links",
    "supply_references",
    "bridges",
}
FIELDS = {
    "id",
    "tag",
    "description",
    "page",
    "installation",
    "location",
    "manufacturer",
    "part_number",
    "quantity",
    "source_tag",
    "source_terminal",
    "target_tag",
    "target_terminal",
    "wire",
    "cable",
    "terminal",
    "strip",
    "address",
    "controller",
    "rack",
    "slot",
    "channel",
    "signal",
    "ip_address",
    "interface",
    "port",
    "cross_reference",
    "function",
    "potential",
    "color",
    "cross_section",
    "name",
    "device_type",
    "medium",
    "flow_direction",
    "supply_kind",
    "voltage",
    "voltage_unit",
    "pressure",
    "pressure_unit",
    "source_installation",
    "source_location",
    "target_installation",
    "target_location",
    "source_reference",
    "target_reference",
}
MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 100_000


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def atomic_json(path: Path, value):
    data = canonical(value).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_report(data: bytes, suffix: str, *, row_tag: str | None = None, delimiter: str | None = None):
    """Parse declared flat report rows. Namespaces remain exact, including Clark notation."""
    if len(data) > MAX_BYTES:
        raise ValueError("Report exceeds 16 MiB; split it into smaller exports")
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    text = data.decode(encoding)
    if suffix == ".json":
        rows = json.loads(text)
        if isinstance(rows, dict):
            rows = rows.get("rows")
        if not isinstance(rows, list):
            raise ValueError("JSON must contain an array or an object with a rows array")
        numbered = list(enumerate(rows, 1))
    elif suffix in {".xml", ".epj"}:
        if not row_tag or len(row_tag) > 256:
            raise ValueError(
                "XML/EPJ requires an exact row_tag; arbitrary native EPJ schemas are not inferred"
            )
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper() or "\x00" in text:
            raise ValueError("DTD, entities and null bytes are not allowed in report XML")
        root = ET.fromstring(text)
        numbered = []
        for element in root.iter(row_tag):
            row = dict(element.attrib)
            for child in element:
                if len(child) or child.tag in row:
                    raise ValueError("XML rows must have unique flat child properties; export a flat report")
                row[child.tag] = child.text or ""
            numbered.append((len(numbered) + 1, row))
        if not numbered:
            raise ValueError("No rows matched row_tag; no snapshot was created")
    elif suffix in {".csv", ".tsv", ".txt"}:
        delimiter = delimiter or ("\t" if suffix == ".tsv" else ",")
        if delimiter not in {",", ";", "\t", "|"}:
            raise ValueError("delimiter must be comma, semicolon, tab or pipe")
        reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("Report must have unique column names")
        numbered = [(i, row) for i, row in enumerate(reader, 2)]
    else:
        raise ValueError(
            "Use CSV, TSV, TXT, JSON or declared flat XML/EPJ reports; ELK/ZW1 are inventory only"
        )
    if not numbered or len(numbered) > MAX_ROWS:
        raise ValueError("Report must contain 1..100000 rows")
    result = []
    for number, row in numbered:
        if not isinstance(row, dict) or len(row) > 200:
            raise ValueError("Each report row must be an object with at most 200 fields")
        clean = {}
        for key, value in row.items():
            if not isinstance(key, str) or not key or len(key) > 256:
                raise ValueError("Invalid report column name or excess CSV columns")
            if isinstance(value, (dict, list)) or value is None:
                raise ValueError("Report values must be scalars; missing CSV cells are not accepted")
            value = str(value)
            if len(value) > 16000:
                raise ValueError("Report field exceeds 16000 characters")
            clean[key] = value
        result.append((number, clean))
    return result


class ExportService:
    def __init__(self, drawings):
        self.drawings = drawings
        self.config = drawings.config
        self.folder = self.config.state / "eplan-exports"

    def import_reports(self, root_id: str, reports: list[dict]):
        from .operation_progress import checkpoint, progress

        if not isinstance(reports, list) or not 1 <= len(reports) <= 32:
            raise ValueError("Supply 1..32 report declarations")
        sources, records, mappings = [], {kind: [] for kind in sorted(KINDS)}, []
        documents = {}
        for declaration in reports:
            checkpoint()
            if not isinstance(declaration, dict) or set(declaration) - {
                "relative_path",
                "kind",
                "field_map",
                "row_tag",
                "delimiter",
                "evidence_relative_path",
            }:
                raise ValueError("Unknown report declaration fields")
            kind = declaration.get("kind")
            if kind not in KINDS:
                raise ValueError("Unknown report kind")
            relative = declaration.get("relative_path")
            if not isinstance(relative, str):
                raise ValueError("relative_path must be a string")
            path = self.config.resolve(root_id, relative)
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("Report exceeds 16 MiB")
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if sha256(path) != digest:
                raise ValueError("Source changed while reading report")
            source = {
                "root_id": root_id,
                "relative_path": path.relative_to(self.config.roots[root_id]).as_posix(),
                "sha256": digest,
                "kind": kind,
            }
            rows = parse_report(
                data,
                path.suffix.lower(),
                row_tag=declaration.get("row_tag"),
                delimiter=declaration.get("delimiter"),
            )
            evidence = {}
            if "evidence_relative_path" in declaration:
                evidence, dependencies = load_row_evidence(
                    self.drawings,
                    root_id,
                    declaration["evidence_relative_path"],
                    {number for number, _ in rows},
                    documents,
                )
                sources.extend(dependencies)
            mapping = declaration.get("field_map")
            if mapping is None:
                # Exact canonical headers only. Localized names and numeric property IDs need explicit mapping.
                mapping = {field: field for field in FIELDS if any(field in row for _, row in rows)}
            if not isinstance(mapping, dict) or not mapping or set(mapping) - FIELDS:
                raise ValueError("field_map must map canonical fields to exact source column names")
            if any(not isinstance(column, str) or not column for column in mapping.values()):
                raise ValueError("field_map values must be column names")
            for number, raw in rows:
                if number % 128 == 0:
                    checkpoint()
                missing = set(mapping.values()) - set(raw)
                if missing:
                    raise ValueError(f"Mapped columns missing from report row {number}: {sorted(missing)}")
                fields = {key: raw[column] for key, column in mapping.items()}
                provenance = {**source, "row": number, "row_tag": declaration.get("row_tag")}
                records[kind].append(
                    {
                        "fields": fields,
                        "raw": raw,
                        "source": provenance,
                        "evidence": "declared_export_record",
                        "native_engine_validated": False,
                        **evidence.get(number, {}),
                    }
                )
            sources.append(source)
            mappings.append({**declaration, "field_map": mapping})
            progress(len(mappings), len(reports) + 1, "stages", "Read report sources; publication pending")
        if sum(map(len, records.values())) > MAX_ROWS:
            raise ValueError("Combined snapshot exceeds 100000 records")
        sources = list({canonical(source): source for source in sources}.values())
        # All sources must still match immediately before publishing the snapshot.
        for source in sources:
            checkpoint()
            if sha256(self.config.resolve(source["root_id"], source["relative_path"])) != source["sha256"]:
                raise ValueError("Source changed before snapshot publication")
        body = {
            "schema_version": 1,
            "sources": sources,
            "mappings": mappings,
            "records": records,
            "limitations": [
                "Declared report rows; no native EPLAN project validation.",
                "Missing exports and filtered-out objects cannot be detected.",
                "Tag-only associations do not prove physical continuity.",
                "Reviewed drawing assertions retain caller interpretation; quote/hash checks do not authenticate reviewers or validate engineering meaning.",
            ],
        }
        identifier = "ep_" + hashlib.sha256(canonical(body).encode()).hexdigest()
        with self.drawings.coordinator.lock("eplan-export:" + identifier):
            checkpoint()
            atomic_json(self.folder / "snapshots" / (identifier + ".json"), body)
        progress(len(reports) + 1, len(reports) + 1, "stages", "Immutable report snapshot published")
        return self.get(identifier)

    def load(self, snapshot_id):
        if not isinstance(snapshot_id, str) or not re.fullmatch(r"ep_[0-9a-f]{64}", snapshot_id):
            raise ValueError("Invalid snapshot_id")
        body = json.loads((self.folder / "snapshots" / (snapshot_id + ".json")).read_bytes())
        if "ep_" + hashlib.sha256(canonical(body).encode()).hexdigest() != snapshot_id:
            raise ValueError("Snapshot integrity verification failed")
        return body

    def freshness(self, body):
        result = []
        for source in body["sources"]:
            try:
                current = sha256(self.config.resolve(source["root_id"], source["relative_path"]))
                state = "current" if current == source["sha256"] else "changed"
            except (OSError, ValueError):
                state = "unavailable"
            result.append({**source, "state": state})
        return result

    def get(self, snapshot_id):
        body = self.load(snapshot_id)
        return {
            "snapshot_id": snapshot_id,
            "counts": {k: len(v) for k, v in body["records"].items()},
            "sources": self.freshness(body),
            "mappings": body["mappings"],
            "limitations": body["limitations"],
        }

    def query(self, snapshot_id, kind, query=None, offset=0, limit=50):
        if kind not in KINDS:
            raise ValueError("Unknown record kind")
        body = self.load(snapshot_id)
        rows = body["records"].get(kind, [])
        if query:
            rows = [r for r in rows if query.casefold() in canonical(r["fields"]).casefold()]
        return {
            "snapshot_id": snapshot_id,
            "kind": kind,
            "sources": self.freshness(body),
            **paginate(rows, offset, limit),
        }

    def checks(self, snapshot_id, offset=0, limit=50):
        body = self.load(snapshot_id)
        findings = []
        for kind, identity in (("devices", "tag"), ("plc_io", "address"), ("network", "ip_address")):
            groups = collections.defaultdict(list)
            for row in body["records"][kind]:
                f = row["fields"]
                if f.get(identity):
                    key = (
                        f.get("installation", ""),
                        f.get("location", ""),
                        f.get("controller", "") if kind == "plc_io" else "",
                        f[identity],
                    )
                    groups[key].append(row["source"])
                else:
                    findings.append(
                        {
                            "code": "missing_identity",
                            "kind": kind,
                            "field": identity,
                            "sources": [row["source"]],
                        }
                    )
            for key, sources in groups.items():
                if len(sources) > 1:
                    findings.append(
                        {
                            "code": "potential_duplicate",
                            "kind": kind,
                            "identity": key,
                            "sources": sources,
                            "certainty": "review_required",
                        }
                    )
        for row in body["records"]["connections"]:
            if not row["fields"].get("source_tag") or not row["fields"].get("target_tag"):
                findings.append({"code": "unresolved_connection_end", "sources": [row["source"]]})
        return {
            "snapshot_id": snapshot_id,
            "scope": "supplied exports only; absence is not compliance",
            "sources": self.freshness(body),
            **paginate(findings, offset, limit),
        }

    def trace(self, snapshot_id, tag, terminal=None, max_depth=10, max_edges=100):
        if not tag or not 1 <= max_depth <= 40 or not 1 <= max_edges <= 200:
            raise ValueError("Supply tag, depth 1..40 and edge budget 1..200")
        body = self.load(snapshot_id)
        # Exact endpoint tuples avoid inventing bridges between different terminals on one device.
        edges = body["records"]["connections"]
        scopes = collections.defaultdict(set)
        for row in body["records"]["devices"]:
            fields = row["fields"]
            if fields.get("tag"):
                scopes[fields["tag"]].add((fields.get("installation", ""), fields.get("location", "")))
        ambiguous_tags = {name for name, values in scopes.items() if len(values) > 1}
        starts = set()
        for edge in edges:
            f = edge["fields"]
            for side in ("source", "target"):
                endpoint = (f.get(side + "_tag", ""), f.get(side + "_terminal", ""))
                if endpoint[0] == tag and (terminal is None or endpoint[1] == terminal):
                    starts.add(endpoint)
        queue = collections.deque((node, 0) for node in sorted(starts))
        visited, used, result, truncated = set(), set(), [], False
        while queue:
            node, depth = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            if node[0] in ambiguous_tags:
                continue
            for index, row in enumerate(edges):
                f = row["fields"]
                a = (f.get("source_tag", ""), f.get("source_terminal", ""))
                b = (f.get("target_tag", ""), f.get("target_terminal", ""))
                if node not in (a, b) or index in used:
                    continue
                if depth >= max_depth or len(result) >= max_edges:
                    truncated = True
                    continue
                used.add(index)
                result.append(row)
                other = b if node == a else a
                # Blank terminal identifiers are retained but cannot act as inferred junctions.
                if other[0] and other[1]:
                    queue.append((other, depth + 1))
        return {
            "snapshot_id": snapshot_id,
            "tag": tag,
            "terminal": terminal,
            "items": result,
            "truncated": truncated,
            "matched_endpoints": sorted(starts),
            "sources": self.freshness(body),
            "status": "ambiguous_start"
            if tag in ambiguous_tags
            else "reported_paths_only"
            if starts
            else "unresolved_start",
            "ambiguous_tags": sorted(ambiguous_tags),
            "limitations": [
                "No internal device bridges or omitted connections inferred.",
                "Full structured device tags are required; scoped tag ambiguity remains unresolved.",
                "No physical continuity or native EPLAN validation.",
            ],
        }

    def compare(self, before_snapshot_id, after_snapshot_id, offset=0, limit=50):
        before, after = self.load(before_snapshot_id), self.load(after_snapshot_id)
        changes = []
        for kind in sorted(KINDS):
            a = collections.Counter(canonical(r["fields"]) for r in before["records"].get(kind, []))
            b = collections.Counter(canonical(r["fields"]) for r in after["records"].get(kind, []))
            for action, delta in (("removed", a - b), ("added", b - a)):
                changes.extend(
                    {"kind": kind, "change": action, "fields": json.loads(key), "count": count}
                    for key, count in sorted(delta.items())
                )
        return {
            "before_snapshot_id": before_snapshot_id,
            "after_snapshot_id": after_snapshot_id,
            "before_sources": self.freshness(before),
            "after_sources": self.freshness(after),
            **paginate(changes, offset, limit),
        }

    def export(self, snapshot_id):
        body = {"snapshot_id": snapshot_id, **self.load(snapshot_id)}
        path = self.folder / "exports" / (snapshot_id + ".json")
        with self.drawings.coordinator.lock("eplan-export:" + snapshot_id):
            atomic_json(path, body)
            if json.loads(path.read_bytes()) != body:
                raise ValueError("Export readback failed")
        return {
            "snapshot_id": snapshot_id,
            "path": str(path),
            "sha256": sha256(path),
            "sources": self.freshness(body),
            "bytes": path.stat().st_size,
        }
