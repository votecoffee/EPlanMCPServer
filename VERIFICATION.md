# Verification

## Repeatable checks

Run from the checkout after installing the reviewed framework wheel and hash-locked dependencies:

```powershell
uv pip install --python .venv/Scripts/python.exe --require-hashes --only-binary :all: --find-links .local/wheels -r requirements-dev-lock.txt
uv pip install --python .venv/Scripts/python.exe --no-deps -e .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/package.py --output .local/packages/EPlanMCPServer-0.3.0.zip
.\.venv\Scripts\python.exe scripts/package.py --verify
uv pip check --python .venv/Scripts/python.exe
```

Tests cover synthetic PDF/DXF extraction, tables/previews, source hashes, indexing/freshness,
device profiles, explicit power/air paths, terminal-bridge boundaries, ambiguous tag scopes,
multi-point I/O, conflicting IP claims, branching/cycles and PDF candidate context,
geometry/electrical evidence, cross-process locking and durable write receipts. Local-reader tests
cover nested XML, UTF-16 links, missing/path-escaping database references, binary byte coordinates,
zlib checksums/corruption/decompression budgets, experimental EOD slot geometry, ZIP member safety,
and Windows ACE reads of a synthetic database with unchanged source hashes. They
also exercise ACE schema/row access in the reduced environment inherited by MCP stdio. EPLAN report tests
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
# Service-manager reporting profile

Run `python -m pytest -q tests/test_management.py` with a dedicated registry. Verify cached versions,
unknown availability, per-instance activity, failed-call accounting, busy/stale denial, concurrent
duplicate blocked receipts, credential-free snapshots and stopped registration on clean shutdown.
Run the shared framework's synthetic management profile separately for independent restart effect
counts and durable uncertain barriers across process/instance lifetimes. Those synthetic effects
are not EPLAN process-restart acceptance.

Verify the pinned framework wheel SHA-256/RECORD, hashed locks, dependency consistency, packaged
runtime and existing 49-tool direct/50-tool framework schemas. Start only a disposable source-free
or synthetic server for manager-row checks. Existing chats/projects must remain untouched. Confirm
the exact plugin ID and actual running/stopped state rather than equating inventory with reporting.
Live process replacement remains unaccepted and disabled until an app-owned supervisor and
cross-chat safe quiescence protocol exist.
