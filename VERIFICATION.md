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

Timestamp-release checks are pure/package-only while held: padded display versus canonical PEP
440/strict SemVer identity, once-stamped source/plugin/README parity, unchanged dependency pins,
manager normalization, CLI `--version`, wheel METADATA/import and source byte-manifest parity.
Native Codex cache/loader and MCP initialization information remain controlled-runtime acceptance;
building or reading a plugin package never enables it. Historical artifacts are retained privately.

The source readiness gate includes pure reporting-startup/join-failure and read-only ADO cleanup
stubs (`test_handle_cleanup.py`); these never start a management listener or COM/native provider.
Retain per-run results privately with the launch-path inventory. Unsupported bootstrap/framework
ownership profiles are implementation gaps; real EOF/crash/descendant/manager checks on the direct
offline profile are runtime acceptance pending authorization. Neither category is ordinary-use
acceptance. See the [launch-path coverage table](docs/resource-ownership.md#launch-path-coverage).

Framework 0.20.0 alignment is source-only. Verify the reviewed wheel SHA-256/RECORD and exact SDK
2.3 pin without installing it during a runtime hold. `test_resource_claims.py` exercises the actual
shared ledger with synthetic process identities; `test_owned_processes.py` replaces all OS process
APIs with stubs. These establish record/adapter behavior, not real Windows containment or manager
orphan cleanup. Installed environments and historical plugin bindings are intentionally unchanged.

Owned-resource lifecycle changes currently have pure Windows-API stub and in-process admission
checks only. They launch no process, job, server, plugin or native application. Full regression,
real Windows containment/parent-death/descendant cleanup, clean client EOF, installed runtime and
cross-manager ledger recovery are pending. See [resource ownership](docs/resource-ownership.md).
Bootstrap and framework startup refusals are intentional pending acceptance; earlier successful
protocol/package checks do not validate the changed launch implementation.

Included report examples are synthetic custom schemas. Native EPLAN projects, vendor report
schemes, project restoration and native check-runs require separate acceptance. Package and
protocol checks do not establish engineering correctness or physical continuity.

The explicit binary text-encoding reader has focused byte-preservation checks for UTF-8,
UTF-16 LE/BE and Windows-1252, malformed sequences and surrogate pairs. Synthetic isolated-worker,
compressed/archive and direct stdio checks passed during development. Full regression and wheel
acceptance after the latest source changes remain pending; do not treat the earlier 125-test run
as acceptance of subsequent changes.

The four-endpoint admission gate currently has in-process lock/capacity/exception-release checks
only. Startup, abrupt parent exit, descendant cleanup and installed-runtime acceptance remain
pending. Do not start a server or validation worker while an operator startup hold is active.

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
runtime and current 50-tool direct/backend schemas (49 original tools plus the shared workflow reader). Start only a disposable source-free
or synthetic server for manager-row checks. Existing chats/projects must remain untouched. Confirm
the exact plugin ID and actual running/stopped state rather than equating inventory with reporting.
Live process replacement remains unaccepted and disabled until an app-owned supervisor and
cross-chat safe quiescence protocol exist.
# Runtime guidance profile

Run `python -m pytest -q tests/test_guidance.py tests/test_framework.py`. Verify the generated
bootstrap, canonical supporting-reference parity, manifest byte hashes, list/get/resource consistency,
connected-client guide and reference updates/removal, stale revision/hash rejection, and failed
publication preserving the prior guide/catalog. Directory reads must remain unadvertised. Source
changes must remain unpublished until explicit revision-checked publication. Repeat protocol checks
against the installed standalone route and an isolated wheel. Native Codex skill selection/reload
and plugin-submission import remain separate host acceptance, not protocol-test results.
