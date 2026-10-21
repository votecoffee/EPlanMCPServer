"""Bind caller-reviewed report rows to indexed PDF text without interpreting the claims."""

from __future__ import annotations

import hashlib
import json
import re

from .service import sha256


def normalized(text):
    return " ".join(text.split())


def load_row_evidence(drawings, root_id, relative_path, row_numbers, documents):
    """Validate a bounded sidecar and return row evidence plus all freshness dependencies.

    Quote matching checks the source binding only. It cannot authenticate a reviewer or prove
    that the quoted text supports the supplied engineering interpretation.
    """
    if not isinstance(relative_path, str):
        raise ValueError("evidence_relative_path must be a relative path string")
    path = drawings.config.resolve(root_id, relative_path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Row evidence sidecar exceeds 4 MiB")
    data = path.read_bytes()
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Row evidence sidecar exceeds 4 MiB")
    digest = hashlib.sha256(data).hexdigest()
    if sha256(path) != digest:
        raise ValueError("Evidence sidecar changed during reading")
    body = json.loads(data)
    if (
        not isinstance(body, dict)
        or set(body) != {"schema", "rows"}
        or body["schema"] != "eplan-row-evidence/1"
        or not isinstance(body["rows"], list)
        or not 1 <= len(body["rows"]) <= 2000
    ):
        raise ValueError("Use eplan-row-evidence/1 with 1..2000 reviewed rows")
    sources = [
        {
            "root_id": root_id,
            "relative_path": path.relative_to(drawings.config.roots[root_id]).as_posix(),
            "sha256": digest,
            "kind": "review_evidence",
        }
    ]
    result = {}
    for row in body["rows"]:
        if not isinstance(row, dict) or set(row) != {"row", "reviewer", "note", "references"}:
            raise ValueError("Evidence rows require row, reviewer, note and references")
        number = row["row"]
        if type(number) is not int or number not in row_numbers or number in result:
            raise ValueError("Evidence row number is duplicate or does not match a report row")
        for key, maximum in (("reviewer", 200), ("note", 2000)):
            if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > maximum:
                raise ValueError(f"Evidence {key} must be nonempty text up to {maximum} characters")
        references = row["references"]
        if not isinstance(references, list) or not 1 <= len(references) <= 8:
            raise ValueError("Each reviewed row requires 1..8 PDF references")
        bound = []
        for ref in references:
            if not isinstance(ref, dict) or set(ref) != {
                "root_id",
                "relative_path",
                "sha256",
                "page",
                "quotes",
            }:
                raise ValueError("PDF references require root_id, relative_path, sha256, page and quotes")
            if not all(isinstance(ref[k], str) for k in ("root_id", "relative_path", "sha256")):
                raise ValueError("PDF reference paths and SHA-256 must be strings")
            if not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]):
                raise ValueError("PDF reference requires a lowercase SHA-256")
            quotes = ref["quotes"]
            if not isinstance(quotes, list) or not 1 <= len(quotes) <= 20:
                raise ValueError("PDF reference requires 1..20 exact text-record quotes")
            if any(not isinstance(q, str) or not normalized(q) or len(q) > 1000 for q in quotes):
                raise ValueError("PDF quotes must be nonempty text up to 1000 characters")
            key = (ref["root_id"], ref["relative_path"], ref["sha256"])
            if key not in documents:
                if len(documents) >= 128:
                    raise ValueError("Reviewed import exceeds 128 distinct drawing references")
                document = drawings.load(ref["root_id"], ref["relative_path"], cached_only=True)
                if document["format"] != "pdf" or document["source"]["sha256"] != ref["sha256"]:
                    raise ValueError("Reviewed reference must match the current indexed PDF SHA-256")
                pages = {}
                for index, record in enumerate(document.get("text", [])):
                    pages.setdefault(record.get("page"), {}).setdefault(
                        normalized(record.get("text", "")), []
                    ).append({"record_index": index, "bbox": record.get("bbox")})
                documents[key] = (document, pages)
            document, pages = documents[key]
            page = ref["page"]
            if type(page) is not int or not 1 <= page <= len(document["pages"]):
                raise ValueError("PDF reference page must be a valid one-based integer")
            matches = []
            for quote in quotes:
                locations = pages.get(page, {}).get(normalized(quote), [])
                if not locations or len(locations) > 100:
                    raise ValueError(
                        "PDF quote must match 1..100 complete text records on the referenced page"
                    )
                matches.append({"quote": quote, "locations": locations})
            source = {**document["source"], "kind": "reviewed_drawing_source"}
            sources.append(source)
            bound.append({"source": source, "page": page, "quotes": matches})
        result[number] = {
            "evidence": "reviewed_drawing_assertion",
            "review": {"reviewer": row["reviewer"], "note": row["note"], "reviewer_authenticated": False},
            "references": bound,
        }
    if set(result) != set(row_numbers):
        raise ValueError("Every reviewed report row requires exactly one evidence entry")
    return result, sources
