# Verification

## Repeatable checks

Run from the checkout after installing the reviewed framework wheel and hash-locked dependencies:

```powershell
uv pip install --python .venv/Scripts/python.exe --require-hashes --only-binary :all: --find-links .local/wheels -r requirements-dev-lock.txt
uv pip install --python .venv/Scripts/python.exe --no-deps -e .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/package.py --output .local/packages/EPlanMCPServer-0.1.0.zip
.\.venv\Scripts\python.exe scripts/package.py --verify
uv pip check --python .venv/Scripts/python.exe
```

Tests cover synthetic PDF/DXF extraction, tables/previews, source hashes, indexing/freshness,
geometry/electrical evidence, cross-process locking and durable write receipts. EPLAN report tests
cover explicit mapping, provenance, stale/deleted sources, duplicate multiplicity, malformed rows,
XML entity rejection, namespaces/UTF-16, path escape, snapshot integrity and concurrent imports.
Real stdio MCP testing initializes the server, discovers schemas/annotations, performs a cold PDF
extraction and exercises import/query/check/trace/compare/export plus receipt replay.

## Acceptance boundaries

Included report examples are synthetic custom schemas. Native EPLAN projects, vendor report
schemes, project restoration and native check-runs require separate acceptance. Package and
protocol checks do not establish engineering correctness or physical continuity.

## Local validation evidence

Store installation receipts, machine details, customer paths, corpus manifests, extracted data,
screenshots and run-specific results under the ignored repository-root `.local/` directory or
outside the checkout. Do not add them to this document, public documentation or examples.

Configure `examples/synthetic` as root `synthetic` to repeat the portable protocol smoke:

```powershell
.\.venv\Scripts\python.exe scripts/protocol_smoke.py --root synthetic --reports examples/synthetic/reports.json
```

Generate archives under `.local/packages/`. Inspect source and wheel contents before publishing;
the source packager excludes private working directories and rejects symbolic links. Keep the
tracked byte manifest current after changing packaged source or documentation.
