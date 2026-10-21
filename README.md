# EPLAN MCP Server _(EPlanMCPServer, eplan-mcp-server)_

Source-preserving EPLAN export, electrical report and drawing analysis for MCP

Standalone Codex plugin, shared Python service and CLI. Version **0.1.0**.
The repository uses `EPlanMCPServer`; the Python distribution uses the normalized package name
`eplan-mcp-server` and imports as `eplan_mcp`.

## Table of Contents

- [Background](#background)
- [Install](#install)
- [Usage](#usage)
- [Features](#features)
- [Optional app-owned framework](#optional-app-owned-framework)
- [Development](#development)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Background

Built using the [AutoCAD MCP Server](https://github.com/votecoffee/AutoCADMCPServer) architecture.
This release analyzes exported evidence without changing engineering sources. It does not require
EPLAN for offline analysis. It does not yet provide native EPLAN project access or editing.

## Install

### Dependencies

Python 3.11+; Windows is the primary target. Python 3.13 is used for validation. ODA File Converter
is optional and required only for DWG/DWT/DWS. DXF, PDF and report analysis work without it.

The shared framework is a separately supplied local wheel, not fetched from an unverified public
package with the same name. The installer verifies SHA-256 and every wheel RECORD member:

```text
universal_codex_tools-0.17.0-py3-none-any.whl
SHA-256 6387265e9353f69f2dd767e4431ab2c7f6df40dd090118592a01daa3b5946c6b
Source commit 87157f88de4a5320d2712224216b1e6f18a0ec8d
```

```powershell
.\InstallAndRun.cmd --framework-wheel C:\Packages\universal_codex_tools-0.17.0-py3-none-any.whl --root "engineering=C:\Engineering\EPLAN-Exports" --install-only
```

Dependencies install into `.venv`; roots, caches, receipts, artifacts and plugin bindings stay
under ignored `.local`. Existing configuration and explicit integration preferences are preserved.
The initial setup refreshes the standalone Codex plugin by default. To skip that integration use
`--codex-integration none`. No customer directories are automatically selected.

After first setup, double-click `InstallAndRun.cmd` for loopback HTTP at port **8816**, or:

```powershell
.\InstallAndRun.cmd --stdio
.\.venv\Scripts\python.exe scripts\install_plugin.py --mode standalone
```

The plugin is `eplan@eplan-local`. Its generated stdio binding starts this application's own
environment. Reconnect Codex or open a fresh chat after installation. Package/protocol checks
do not prove activation in an already-open chat.

## Usage

Start with `eplan_status` and `eplan_capabilities`. Select named roots using `eplan_list_files`.
Native project files can be included with `supported_only=false`; drawing extraction filters do
not enumerate report formats as supported drawings. Reports are imported through their own tool.

Example `eplan_import_reports` arguments:

```json
{
  "root_id": "engineering",
  "reports": [
    {"relative_path": "devices.csv", "kind": "devices",
     "field_map": {"tag": "Device designation", "description": "Function text"}},
    {"relative_path": "connections.csv", "kind": "connections",
     "field_map": {"source_tag": "Source DT", "source_terminal": "Source terminal",
                   "target_tag": "Target DT", "target_terminal": "Target terminal"}}
  ],
  "request_id": "import-reviewed-exports-001"
}
```

Mappings are **canonical name Ã¢â€ â€™ exact exported column/property**. No localized labels, numeric
property IDs or export scheme are guessed. Exact canonical headers can omit field_map. CSV uses
comma by default; TSV uses tab. Set delimiter explicitly for semicolon or pipe exports. UTF-8/BOM
and BOM-marked UTF-16 are supported. XML requires exact row_tag (Clark notation for namespaces).
Limits: 16 MiB/report, 32 declarations, 100000 combined rows, 200 properties/row, 16000 chars/property.
Input XML must have flat rows with unique child properties; DTD/entities are rejected.

The result supplies `snapshot_id`:

| Tool | Purpose |
| --- | --- |
| `eplan_get_export_snapshot` | Counts, mappings, freshness and limitations |
| `eplan_query_export` | Paginated records by kind and optional literal query |
| `eplan_check_exports` | Potential duplicates and missing identities/endpoints |
| `eplan_trace_export_connection` | Exact tag/terminal paths from connection rows |
| `eplan_compare_export_snapshots` | Added/removed mapped rows with multiplicity |
| `eplan_export_snapshot` | Readback-verified JSON artifact and hash |

Kinds: `devices`, `connections`, `plc_io`, `terminals`, `cables`, `parts`, `network`, `pages`.
Use full structured device tags. Different terminals on a device are not internally bridged.
Findings are review observations: repeated tags can represent legitimate multi-function devices.
Historical snapshots remain readable when sources change or disappear; always inspect freshness.

For drawings, index bounded batches with `eplan_index_project`, then use `eplan_search_project`.
Inspect failures and coverage. Use `eplan_get_text`, `eplan_get_entities`, `eplan_get_pdf_tables`
and `eplan_render_preview` for source detail. Drawing-derived electrical snapshots use their own
`project_id` and `eplan_build_electrical_project` workflow, separate from EPLAN `snapshot_id`.

### CLI

The CLI uses the same service:

```powershell
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json status
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json import-reports engineering declarations.json
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json snapshot-query ep_HASH devices --limit 20
```

Synthetic examples are in `examples/synthetic`; these are custom test reports, not authenticated
vendor-generated exports. Configure that directory as a source root to try `reports.json`.

### Python

The Python API uses the same service as the CLI and MCP adapters:

```python
from eplan_mcp.config import Config
from eplan_mcp.exports import ExportService
from eplan_mcp.service import DrawingService

drawings = DrawingService(Config.load(".local/config.json"))
exports = ExportService(drawings)
snapshot = exports.import_reports(
    "engineering",
    [{"relative_path": "devices.csv", "kind": "devices", "field_map": {"tag": "Device designation"}}],
)
devices = exports.query(snapshot["snapshot_id"], "devices", limit=20)
```

For every state-writing MCP call retain a unique request_id. Inspect `eplan_get_transaction` after
a lost response. Never automatically replace an uncertain request with a new ID or switch routes.
Sources and state directories must not overlap. Tool arguments cannot select executables or output paths.

## Features

- Import explicitly mapped CSV/TSV/TXT, JSON and flat XML report rows for devices, connections,
  PLC I/O, terminals, cables, parts, network inventory and pages.
- Keep raw properties, canonical mappings, source SHA-256, row provenance and source freshness.
- Query immutable snapshots, review potential duplicate tags/addresses, trace explicit connection
  endpoints, compare revisions including duplicate multiplicity, and export verified JSON evidence.
- Inspect PDF/DXF and ODA-converted DWG/DWT/DWS: text, attributes, layers, blocks, dimensions,
  references, PDF pages/tables, previews, literal project search and drawing comparisons.
- Analyze derivative drawing electrical devices, PLC I/O, equipment groups and connection evidence.
  WDP and AutoCAD Electrical reports remain a separate compatibility workflow.
- Bound responses and worker concurrency; coordinate shared state across processes; record durable
  write receipts and recover lost replies without silently repeating effects.
- Use 38 direct MCP tools, or the optional app-owned shared-framework host. No universal daemon required.

**Boundaries:** ELK/EDB/ZW1/ZW9/macros are inventory only. Arbitrary native EPJ schemas are not
decoded; only declared flat XML rows can be read. No native project editing, save/upgrade,
restore, UI highlighting, controller access, network scanning or automatic OCR exists.
Export completeness, native check-run results and physical continuity are not established.

## Optional app-owned framework

The direct standalone endpoint is the default. To prepare a dedicated host:

```powershell
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json framework-prepare --host-state .local/framework-host
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json framework-serve --host-state .local/framework-host
```

Use `--frontend framework --host-state .local/framework-host` with `scripts/install_plugin.py`
only after preparing and starting that host. It pins immutable backend bytes and configuration,
uses independent host/app receipts, and exposes the current workflow through `eplan_get_workflow`.
Tasks, remote access, OAuth, replication and native UI integration are not enabled by this app.

## Development

See [VERIFICATION.md](VERIFICATION.md) for repeatable checks and [native integration boundaries](docs/eplan-native-integration.md).
Run tests before committing; packages use an explicit source allowlist and byte manifest.
Keep private engineering content and runtime state out of Git and distributable artifacts.

## Maintainers

[votecoffee](https://github.com/votecoffee). Issues and contributions: use this repository's GitHub issues.

## Contributing

Questions and bug reports are welcome in [GitHub issues](https://github.com/votecoffee/EPlanMCPServer/issues).
Pull requests are accepted. Keep operations in the shared service layer, add relevant synthetic
tests, run the checks in [VERIFICATION.md](VERIFICATION.md), and update documentation and the byte
manifest. Never submit customer projects, real reports, private paths, credentials or local setup
receipts. Use repository-root `.local/` for private working material; it is ignored by Git and excluded
from release packages. Public examples and fixtures must be synthetic or explicitly redistributable.

## License

[MIT](LICENSE) Â© 2026 votecoffee. See [NOTICE.md](NOTICE.md) for attribution.
