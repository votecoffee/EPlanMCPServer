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

## Initial environment

Windows, Python 3.13.9, MCP SDK 2.3.0, framework 0.17.0. Framework wheel SHA-256:
`6387265e9353f69f2dd767e4431ab2c7f6df40dd090118592a01daa3b5946c6b`.
Wheel identity, RECORD members and license are verified before installation.

The inherited AutoCAD lock contained an incorrect hash for the PyMuPDF 1.28.2 Windows AMD64
wheel. Installation rejected it. Both EPLAN locks were corrected against the exact
`pymupdf-1.28.2-cp310-abi3-win_amd64.whl` hash in the official
[PyPI release metadata](https://pypi.org/pypi/pymupdf/1.28.2/json):
`ebd244918798502d7b4504c90410d1711a4d7675a32584ca30f1bab419ecbffe`.
Hash checking was retained; no source-build bypass was accepted.

## Acceptance boundaries

All included report examples are synthetic custom schemas. No customer content is committed.
No native EPLAN instance, license, vendor-generated report scheme, ELK/ZW1 restoration or
native check-run has been accepted. Package and protocol results do not prove live Codex UI
reload, native EPLAN behavior, engineering correctness or physical continuity.

## Results — October 21, 2026

- 71 tests passed, including real MCP stdio, framework catalog/schema parity and routed
  export writes, immutable deployment tamper rejection, plugin relocation and report ambiguity.
- Ruff checks and formatting passed; dependency check found all installed packages compatible.
- Source ZIP inventory and every member's bytes verified against the generated manifest.
- Wheel (27 members) and source distribution inspected; private state and environments excluded.
- A separate environment installed hash-locked dependencies plus the built wheel and passed the
  real MCP smoke test: 38 tools, synthetic import, device/connection/PLC queries.
- The Windows setup launcher completed, preserved the explicit synthetic source configuration,
  and installed `eplan@eplan-local` version 0.1.0 through the Codex plugin CLI.
- Only included synthetic examples were configured. No customer project roots were selected.

To repeat the synthetic protocol smoke after configuring `examples/synthetic` as root `synthetic`:

```powershell
.\.venv\Scripts\python.exe scripts/protocol_smoke.py --root synthetic --reports examples/synthetic/reports.json
```

Source archive, wheel and source distribution are generated under ignored `.local/packages/`.
The local standalone binding points to this checkout's environment. A fresh chat/reconnection
is still needed to establish live Codex UI activation.
