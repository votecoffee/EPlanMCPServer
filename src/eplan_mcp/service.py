from __future__ import annotations

import collections
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import ezdxf
import pymupdf

from . import EXTRACTION_VERSION, __package_version__, __version__
from .config import PROFILE, SUPPORTED, Config
from .coordination import Coordinator
from .owned_processes import run as run_owned
from .worker_launch import worker_command


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bounded(value):
    """Bound each record, explicitly flagging large fields; full text has a slice tool."""
    if not isinstance(value, dict):
        return value
    result = dict(value)
    for key, item in list(result.items()):
        if isinstance(item, str) and len(item) > 8000:
            result[key] = item[:8000]
            result[key + "_truncated"] = True
            result[key + "_total_chars"] = len(item)
        elif isinstance(item, list) and len(item) > 256:
            result[key] = item[:256]
            result[key + "_truncated"] = True
            result[key + "_total_items"] = len(item)
        elif isinstance(item, dict):
            result[key] = bounded(item)
    return result


def paginate(rows: list, offset: int = 0, limit: int = 100) -> dict:
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("offset must be nonnegative and limit must be 1..200")
    selected, size = [], 0
    for original in rows[offset : offset + limit]:
        row = bounded(original)
        length = len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
        if length > 180_000:
            row = {
                "record_omitted": True,
                "reason": "Record exceeds response budget",
                **{k: original[k] for k in ("handle", "type", "page", "record_index") if k in original},
            }
            length = len(json.dumps(row))
        if selected and size + length > 180_000:
            break
        selected.append(row)
        size += length
    end = offset + len(selected)
    return {
        "items": selected,
        "total": len(rows),
        "offset": offset,
        "next_offset": end if end < len(rows) else None,
    }


class DrawingService:
    def __init__(self, config: Config):
        if config.oda_executable is not None:
            raise ValueError("Vendor/native converters are disabled in the offline profile")
        self.config = config
        self.coordinator = Coordinator(
            config.state, config.lock_timeout_seconds, config.max_worker_processes, config.max_oda_processes
        )
        for name in ("cache", "scratch", "previews"):
            (config.state / name).mkdir(parents=True, exist_ok=True)
        self.signature = hashlib.sha256(
            json.dumps(
                {
                    "schema": EXTRACTION_VERSION,
                    "ezdxf": ezdxf.__version__,
                    "pymupdf": pymupdf.VersionBind,
                    "oda": sha256(config.oda_executable) if config.oda_executable else None,
                    "extractor": sha256(Path(__file__).with_name("extract.py")),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        with self.coordinator.lock("index-schema"), self.database() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents(
                    root TEXT, path TEXT, sha TEXT, signature TEXT, indexed_at REAL,
                    PRIMARY KEY(root,path));
                CREATE TABLE IF NOT EXISTS records(
                    root TEXT, path TEXT, record_index INTEGER, text TEXT, location TEXT);
                CREATE INDEX IF NOT EXISTS record_source ON records(root,path);
            """)

    @contextlib.contextmanager
    def database(self):
        db = sqlite3.connect(self.config.state / "index.sqlite3", timeout=30)
        db.execute("PRAGMA busy_timeout=30000")
        db.create_function("CASEFOLD", 1, lambda text: text.casefold())
        try:
            with db:
                yield db
        finally:
            db.close()

    def status(self) -> dict:
        return {
            "name": "EPLAN MCP Server",
            "version": __version__,
            "package_version": __package_version__,
            "profile": PROFILE,
            "roots": {k: str(v) for k, v in self.config.roots.items()},
            "state_dir": str(self.config.state),
            "supported_extensions": sorted(SUPPORTED),
            "oda_available": bool(self.config.oda_executable),
            "oda_executable": str(self.config.oda_executable) if self.config.oda_executable else None,
            "engines": {"ezdxf": ezdxf.__version__, "PyMuPDF": pymupdf.VersionBind},
            "extraction_signature": self.signature,
            "concurrency": {
                "max_concurrent_requests_per_process": self.config.max_concurrent_requests,
                "max_queued_requests_per_process": self.config.max_queued_requests,
                "max_worker_processes_per_state": self.config.max_worker_processes,
                "max_oda_processes_per_state": self.config.max_oda_processes,
                "lock_timeout_seconds": self.config.lock_timeout_seconds,
                "coordination": "Cross-process cache/index locks; WAL index transactions; atomic snapshots/exports",
            },
            "limits": {
                "max_file_bytes": self.config.max_file_bytes,
                "worker_timeout_seconds": self.config.worker_timeout,
                "response_bytes": 200_000,
            },
            "limitations": [
                "DWG/DWT/DWS conversion and Access/ACE provider reads are disabled in the offline profile.",
                "DGN/DWF/DWFx, STEP/IGES, SolidWorks and eDrawings: inventory only.",
                "Only offline DXF/PDF and explicit reports/local byte structures are supported; no vendor discovery.",
                "No CAD editing, network reference loading or automatic OCR; native EPLAN access is unavailable in this offline service.",
            ],
            "electrical_inputs": [
                "WDP project membership",
                "Electrical CSV/TSV/JSON reports",
                "DXF block attributes (DWG inventory only)",
                "PDF text candidates",
            ],
            "electrical_analysis_requires_current_index": True,
            "native_eplan": {
                "connected": False,
                "project_formats": "ELK/ELL link text and raw EOD/EOX evidence readable independently; ZW1/ZW9 inventory only",
            },
        }

    def inventory(self, root_id: str, supported_only=True, offset=0, limit=100) -> dict:
        rows = self.config.files(root_id)
        if supported_only:
            rows = [row for row in rows if row["supported"]]
        return paginate(rows, offset, limit)

    def load(self, root_id: str, relative_path: str, *, cached_only: bool = False) -> dict:
        path = self.config.resolve(root_id, relative_path)
        extension = path.suffix.lower()
        if extension not in SUPPORTED:
            raise ValueError(f"Extraction is not supported for {extension}; inventory only")
        before = sha256(path)
        cache_key = hashlib.sha256(f"{before}:{extension}:{self.signature}".encode()).hexdigest()
        cached = self.config.state / "cache" / (cache_key + ".json")
        if not cached.exists():
            with self.coordinator.lock("cache:" + cache_key):
                if not cached.exists():
                    if cached_only:
                        raise ValueError(
                            "Current extraction cache is missing; run eplan_index_project before electrical analysis"
                        )
                    self._extract_to_cache(path, extension, before, cached)
        data = json.loads(cached.read_text(encoding="utf-8"))
        if sha256(path) != before:
            raise ValueError("Source changed while reading the cache")
        return {
            **data,
            "source": {
                "root_id": root_id,
                "relative_path": relative_path,
                "sha256": before,
                "size_bytes": path.stat().st_size,
                "extraction_signature": self.signature,
            },
        }

    def _extract_to_cache(self, path, extension, before, cached):
        with tempfile.TemporaryDirectory(dir=self.config.state / "scratch") as folder:
            scratch = Path(folder)
            source = scratch / ("source" + extension)
            shutil.copyfile(path, source)
            if sha256(source) != before or sha256(path) != before:
                raise ValueError("Source changed during snapshot; retry against a stable source")
            destination = scratch / "extraction.json"
            options = {
                "oda_executable": str(self.config.oda_executable) if self.config.oda_executable else None,
                "max_entities": self.config.max_entities,
                "max_pages": self.config.max_pages,
            }
            args = worker_command(
                "_extract",
                str(source),
                str(destination),
                json.dumps(options),
            )
            opts = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            try:
                # A Windows venv launcher can stall when it inherits the active MCP input pipe.
                # Workers take all input through argv/files and must never read that pipe.
                with self.coordinator.worker(native=extension in {".dwg", ".dwt", ".dws"}):
                    completed = run_owned(
                        args,
                        check=False,
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        timeout=self.config.worker_timeout,
                        encoding="utf-8",
                        errors="replace",
                        **opts,
                    )
            except subprocess.TimeoutExpired as error:
                raise ValueError("Extraction worker timed out; no partial result published") from error
            if completed.returncode != 0 or not destination.exists():
                raise ValueError("Extraction worker failed: " + completed.stderr[-3000:])
            data = json.loads(destination.read_text(encoding="utf-8"))
            if sha256(path) != before:
                raise ValueError("Source changed during extraction; result discarded")
            # Concurrent clients can race safely: immutable content key, atomic cache publication.
            temp = cached.with_name(cached.name + "." + uuid.uuid4().hex + ".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            os.replace(temp, cached)

    def inspect(self, root_id: str, relative_path: str) -> dict:
        doc = self.load(root_id, relative_path)
        return {
            key: doc[key] for key in ("source", "format", "backend", "metadata", "counts", "warnings")
        } | {
            "layouts": doc.get("layouts", []),
            "pdf_page_count": len(doc.get("pages", [])),
            "text_records": len(doc["text"]),
            "layers": len(doc["layers"]),
            "blocks": len(doc["blocks"]),
            "external_references": len(doc["references"]),
            "ocr_candidate_pages": [p["page"] for p in doc.get("pages", []) if p["ocr_candidate"]],
        }

    def records(
        self,
        root_id: str,
        relative_path: str,
        collection: str,
        offset=0,
        limit=100,
        layout: str | None = None,
        layer: str | None = None,
        entity_type: str | None = None,
        page: int | None = None,
        handle: str | None = None,
        query: str | None = None,
        block: str | None = None,
    ) -> dict:
        if collection not in {"entities", "text", "layers", "blocks", "references", "pages"}:
            raise ValueError("Unknown record collection")
        doc = self.load(root_id, relative_path)
        rows = [{**row, "record_index": index} for index, row in enumerate(doc.get(collection, []))]
        for key, value in (
            ("layout", layout),
            ("layer", layer),
            ("type", entity_type),
            ("page", page),
            ("handle", handle),
            ("block_definition", block),
        ):
            if value is not None:
                rows = [row for row in rows if row.get(key) == value]
        if query is not None:
            rows = [row for row in rows if query.casefold() in row.get("text", "").casefold()]
        return {"source": doc["source"], "collection": collection, **paginate(rows, offset, limit)}

    def text_slice(self, root_id: str, relative_path: str, record_index: int, start=0, length=8000) -> dict:
        if start < 0 or not 1 <= length <= 16000 or record_index < 0:
            raise ValueError("Invalid text slice; length must be 1..16000")
        doc = self.load(root_id, relative_path)
        row = doc["text"][record_index]
        text = row["text"]
        return {
            "source": doc["source"],
            "record_index": record_index,
            "start": start,
            "text": text[start : start + length],
            "total_chars": len(text),
            "next_start": start + length if start + length < len(text) else None,
        }

    def index(self, root_id: str, offset=0, limit=2) -> dict:
        from .operation_progress import checkpoint, progress

        if not 1 <= limit <= 5:
            raise ValueError("Index batches contain 1..5 files; follow next_offset")
        batch = self.inventory(root_id, True, offset, limit)
        results = []
        started = time.monotonic()
        for file in batch["items"]:
            checkpoint()
            if results and time.monotonic() - started > 150:
                break
            relative_path = file["relative_path"]
            try:
                doc = self._index_file(root_id, relative_path)
                results.append(
                    {
                        "path": relative_path,
                        "status": "indexed",
                        "records": len(doc["text"]),
                        "sha256": doc["source"]["sha256"],
                    }
                )
            except (ValueError, OSError, RuntimeError, KeyError) as error:
                results.append({"path": relative_path, "status": "failed", "error": str(error)[:3000]})
            progress(len(results), len(batch["items"]), "files", "Processed drawing files")
        checkpoint()
        return {
            "root_id": root_id,
            "results": results,
            "total_files": batch["total"],
            "next_offset": offset + len(results) if offset + len(results) < batch["total"] else None,
        }

    def _index_file(self, root_id, relative_path):
        path = self.config.resolve(root_id, relative_path)
        with self.coordinator.lock("index:" + root_id + ":" + str(path)):
            doc = self.load(root_id, relative_path)
            with self.database() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM records WHERE root=? AND path=?", (root_id, relative_path))
                db.executemany(
                    "INSERT INTO records VALUES(?,?,?,?,?)",
                    (
                        (
                            root_id,
                            relative_path,
                            i,
                            row["text"],
                            json.dumps({k: v for k, v in row.items() if k != "text"}),
                        )
                        for i, row in enumerate(doc["text"])
                    ),
                )
                db.execute(
                    "INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?)",
                    (root_id, relative_path, doc["source"]["sha256"], self.signature, time.time()),
                )
                if sha256(self.config.resolve(root_id, relative_path)) != doc["source"]["sha256"]:
                    raise ValueError("Source changed before index commit; previous index preserved")
            return doc

    def search(self, root_id: str, query: str, offset=0, limit=50) -> dict:
        if not query.strip() or len(query) > 500:
            raise ValueError("Supply a nonempty literal query of at most 500 characters")
        files = self.inventory(root_id, True, 0, 200)
        all_files = self.config.files(root_id)
        supported = [row for row in all_files if row["supported"]]
        current, stale, missing = {}, [], []
        with self.database() as db:
            db.execute("BEGIN")
            indexed = {
                path: (digest, signature)
                for path, digest, signature in db.execute(
                    "SELECT path,sha,signature FROM documents WHERE root=?", (root_id,)
                )
            }
            for file in supported:
                path = file["relative_path"]
                if path not in indexed:
                    missing.append(path)
                    continue
                digest, signature = indexed[path]
                if signature != self.signature or sha256(self.config.resolve(root_id, path)) != digest:
                    stale.append(path)
                else:
                    current[path] = digest
            matches = []
            for path, index, text, location in db.execute(
                "SELECT path,record_index,text,location FROM records WHERE root=? AND instr(CASEFOLD(text),?)>0 "
                "ORDER BY path,record_index",
                (root_id, query.casefold()),
            ):
                if path in current:
                    pos = text.casefold().find(query.casefold())
                    matches.append(
                        {
                            "relative_path": path,
                            "sha256": current[path],
                            "record_index": index,
                            "snippet": text[max(0, pos - 120) : pos + len(query) + 240],
                            "location": json.loads(location),
                        }
                    )
        return {
            "root_id": root_id,
            "query": query,
            **paginate(matches, offset, limit),
            "coverage": {
                "supported_files": files["total"],
                "current_indexed_files": len(current),
                "unindexed_files": len(missing),
                "stale_files": len(stale),
                "complete": not missing and not stale,
                "unindexed_examples": missing[:20],
                "stale_examples": stale[:20],
            },
        }

    def compare(
        self,
        root_id: str,
        relative_path: str,
        other_root_id: str,
        other_relative_path: str,
        offset=0,
        limit=100,
    ) -> dict:
        left, right = self.load(root_id, relative_path), self.load(other_root_id, other_relative_path)
        changes = []
        for category, key in (("text", "text"), ("layers", "name"), ("blocks", "name")):
            a = collections.Counter(row[key] for row in left[category])
            b = collections.Counter(row[key] for row in right[category])
            for value in sorted(a.keys() | b.keys()):
                if a[value] != b[value]:
                    changes.append(
                        {
                            "category": category,
                            "value": value,
                            "before_count": a[value],
                            "after_count": b[value],
                        }
                    )
        return {
            "before": left["source"],
            "after": right["source"],
            **paginate(changes, offset, limit),
            "scope": "Exact text multiset and layer/block names. No geometric or visual equivalence claim.",
        }

    def render(self, root_id: str, relative_path: str, page=1, layout="Model", width=1600) -> dict:
        if not 1 <= width <= 3000 or page < 1:
            raise ValueError("width must be 1..3000; page is one-based")
        # Reuse the snapshot worker boundary for native and parser rendering.
        source_doc = self.load(root_id, relative_path)
        source = self.config.resolve(root_id, relative_path)
        filename = uuid.uuid4().hex + ".png"
        target = self.config.state / "previews" / filename
        with tempfile.TemporaryDirectory(dir=self.config.state / "scratch") as folder:
            staged = Path(folder) / ("source" + source.suffix.lower())
            shutil.copyfile(source, staged)
            if sha256(staged) != source_doc["source"]["sha256"]:
                raise ValueError("Source changed before rendering")
            args = worker_command(
                "_render",
                str(staged),
                str(target),
                json.dumps(
                    {
                        "page": page,
                        "layout": layout,
                        "width": width,
                        "oda_executable": str(self.config.oda_executable)
                        if self.config.oda_executable
                        else None,
                    }
                ),
            )
            opts = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            with self.coordinator.worker(native=source.suffix.lower() in {".dwg", ".dwt", ".dws"}):
                result = run_owned(
                    args,
                    check=False,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=self.config.worker_timeout,
                    encoding="utf-8",
                    errors="replace",
                    **opts,
                )
            if result.returncode or not target.exists():
                raise ValueError("Preview failed: " + result.stderr[-3000:])
        if sha256(source) != source_doc["source"]["sha256"]:
            raise ValueError("Source changed during rendering; preview is not current")
        return {
            "source": source_doc["source"],
            "preview_path": str(target),
            "sha256": sha256(target),
            "page": page if source_doc["format"] == "pdf" else None,
            "layout": layout if source_doc["format"] == "cad" else None,
            "scope": "Approximate ezdxf preview" if source_doc["format"] == "cad" else "PDF raster preview",
        }

    def pdf_tables(self, root_id: str, relative_path: str, page: int, offset=0, limit=20) -> dict:
        doc = self.load(root_id, relative_path)
        if doc["format"] != "pdf" or page < 1 or page > len(doc["pages"]):
            raise ValueError("Supply a PDF and a valid one-based page")
        source = self.config.resolve(root_id, relative_path)
        with tempfile.TemporaryDirectory(dir=self.config.state / "scratch") as folder:
            staged = Path(folder) / "source.pdf"
            destination = Path(folder) / "tables.json"
            shutil.copyfile(source, staged)
            if sha256(staged) != doc["source"]["sha256"]:
                raise ValueError("Source changed before table detection")
            opts = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
            with self.coordinator.worker():
                result = run_owned(
                    worker_command(
                        "_tables",
                        str(staged),
                        str(destination),
                        json.dumps({"page": page}),
                    ),
                    check=False,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=self.config.worker_timeout,
                    encoding="utf-8",
                    errors="replace",
                    **opts,
                )
            if result.returncode or not destination.exists():
                raise ValueError("PDF table worker failed: " + result.stderr[-3000:])
            rows = json.loads(destination.read_text(encoding="utf-8"))
        if sha256(source) != doc["source"]["sha256"]:
            raise ValueError("Source changed during table detection")
        return {
            "source": doc["source"],
            **paginate(rows, offset, limit),
            "warning": "Heuristic PDF table detection; verify cells against the page preview.",
        }
