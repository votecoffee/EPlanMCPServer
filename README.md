# EPLAN MCP Server _(EPlanMCPServer, eplan-mcp-server)_

Source-preserving EPLAN export, electrical report and drawing analysis for MCP

Standalone Codex plugin, shared Python service and CLI. Version **0.3.0**.
The main purpose is to extract device names/descriptions, network addresses, PLC I/O points,
and the power or compressed-air supplies feeding each device.
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

**Lifecycle transition:** bootstrap installation and the optional framework serve/proxy routes
currently refuse startup pending owned-resource acceptance. The direct Windows process-containment
implementation is source-tested with OS stubs only. Do not use it as an accepted production
cleanup profile. See [resource ownership](docs/resource-ownership.md) for limits and pending checks.
Installation examples below describe the retained setup workflow once that gate is resolved.

### Dependencies

Python 3.11+; Windows is the primary target. Python 3.13 is used for validation. ODA File Converter
is optional and required only for DWG/DWT/DWS. DXF, PDF and report analysis work without it.

The shared framework is a separately supplied local wheel, not fetched from an unverified public
package with the same name. The installer verifies SHA-256 and every wheel RECORD member:

```text
universal_codex_tools-0.18.0-py3-none-any.whl
SHA-256 0c1084b424f079957ebd3bec763e609564aaef64cd1fedee78b61a45bfbc24ac
Source commit 7d8a0ccdc06598313061147ee8774837118a8861
```

```powershell
.\InstallAndRun.cmd --framework-wheel C:\Packages\universal_codex_tools-0.18.0-py3-none-any.whl --root "engineering=C:\Engineering\EPLAN-Exports" --install-only
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
Local data files can be included with `supported_only=false`; drawing extraction filters do
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

Mappings are **canonical name to exact exported column/property**. No localized labels, numeric
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

Kinds: `devices`, `connections`, `plc_io`, `terminals`, `cables`, `parts`, `network`, `pages`,
`supplies`, `supply_links`, `bridges`.
Use full structured device tags. Different terminals on a device are not internally bridged.
Findings are review observations: repeated tags can represent legitimate multi-function devices.
Historical snapshots remain readable when sources change or disappear; always inspect freshness.

For drawings, index bounded batches with `eplan_index_project`, then use `eplan_search_project`.
Inspect failures and coverage. Use `eplan_get_text`, `eplan_get_entities`, `eplan_get_pdf_tables`
and `eplan_render_preview` for source detail. Drawing-derived electrical snapshots use their own
`project_id` and `eplan_build_electrical_project` workflow, separate from EPLAN `snapshot_id`.

### Device information and supply feeds

Use `eplan_get_device_profile` for exact-tag names/descriptions, IP/interface facts, PLC I/O and
power/air supply summaries. Use `eplan_trace_device_supply` to follow explicitly declared terminal
relationships upstream to reported source outputs. Electrical and pneumatic domains stay separate.
Connections require explicit media and flow direction; internal terminal bridges are never invented.
Ambiguity, multiple feeds, conflicting facts, missing ports and incomplete paths remain explicit.

Use `eplan_collect_device_evidence` to find device text, IP literals, I/O labels and nearby power/air
context in indexed drawings. These are candidates with hashes and positions; text proximity does
not establish device ownership or feed connectivity. Counts are occurrences, not unique devices.

See [device information](docs/device-information.md) for the report contract, synthetic example,
scope handling and coverage limits.

### Independent local readers

These tools work without starting EPLAN or checking out an EPLAN license. They read isolated
copies; every response identifies the original source hash. Windows Access reads require the
installed Microsoft Access Database Engine (ACE) OLE DB provider matching Python's architecture.
No Access installation or provider is downloaded automatically.

| Tool | Content access |
| --- | --- |
| `eplan_read_xml` | Discover tags; query exact records including nested properties |
| `eplan_read_access` | List local base tables; read paginated rows and column types |
| `eplan_read_project_link` | Decode ELK/ELL references and inventory an in-root EDB folder |
| `eplan_read_archive` | List ordinary ZIP members; run a bounded reader on one exact member |
| `eplan_read_binary_bytes` | Inspect raw or inflated byte ranges as hex |
| `eplan_read_binary_text` | Read ASCII-compatible text candidates with byte offsets |
| `eplan_find_compressed_streams` | Discover checksum-valid zlib streams in bounded windows |
| `eplan_read_eod_slots` | Experimental fixed-slot partitioning and raw headers |

For binary reads, byte offsets refer to the source file unless `stream_offset` selects an
inflated stream. Inflated results include the stream's source offset, consumed byte length and
inflated hash. Follow scan continuation and result pagination separately. Binary matches can
include incidental strings, stale data or window-edge fragments; they are not verified devices,
pages, connections or active objects. See [local reader details](docs/local-readers.md).

For non-ASCII descriptions, explicitly select `text_encoding` (`utf-8`, `utf-16-le`, `utf-16-be`
or `cp1252`) on `eplan_read_binary_text`, including inflated streams. Results preserve exact byte
offsets and lengths; invalid units split candidates. No character encoding or device ownership is guessed.

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

- Independently inspect nested XML records, Windows Access base tables, ELK/ELL project links,
  ordinary ZIP members, raw binary byte ranges and offset-bound text candidates.
- Discover and inflate checksum-valid zlib streams in binary data with strict resource budgets.
  Experimental EOD slot partitioning exposes raw headers; it does not infer native object status.

- Import explicitly mapped CSV/TSV/TXT, JSON and flat XML report rows for devices, connections,
  PLC I/O, terminals, cables, parts, network inventory and pages.
- Keep raw properties, canonical mappings, source SHA-256, row provenance and source freshness.
- Query immutable snapshots, review potential duplicate tags/addresses, trace explicit connection
  endpoints, compare revisions including duplicate multiplicity, and export verified JSON evidence.
- Inspect PDF/DXF and ODA-converted DWG/DWT/DWS: text, attributes, layers, blocks, dimensions,
  references, PDF pages/tables with cell coordinates, previews, literal project search and drawing comparisons.
  Drawing I/O candidates include I/Q and bracketed DI/DO, AI/AO, GI/GO and UI/UO address text.
  Air candidates include plant-air, feed, preparation, manifold and dump-valve labels.
  [Reviewed drawing records](docs/reviewed-drawing-records.md) retain original PDF hashes, page quotes
  and reviewer notes in device facts and supply traces, with original-source freshness checks.
  Device answers also retain reported feed/sheet references when terminal connectivity is unresolved.
- Analyze derivative drawing electrical devices, PLC I/O, equipment groups and connection evidence.
  WDP and AutoCAD Electrical reports remain a separate compatibility workflow.
- Bound responses and worker concurrency; coordinate shared state across processes; record durable
  write receipts and recover lost replies without silently repeating effects.
- Use 49 direct MCP tools, or the optional app-owned shared-framework host. No universal daemon required.

**Boundaries:** ZW1/ZW9/macros remain inventory only. ELK/ELL links and raw/decompressed EOD/EOX
evidence can be read independently; full semantic project decoding is not provided. Nested XML
can be inspected, while canonical report imports still require flat explicitly mapped rows. No native project editing, save/upgrade,
restore, UI highlighting, controller access, network scanning or automatic OCR exists.
Export completeness, native check-run results and physical continuity are not established.

## Optional app-owned framework

Serving and proxy startup are currently blocked pending backend-tree and shared-owner lifetime
acceptance. The following describes the retained design; it is not permission to start the profile.

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

`eplan_capabilities.feature_profiles` reports enabled/tested features and concrete blockers.
[Feature profiles](docs/feature-profiles.md) cover progress, cooperative cancellation, private
report resources, bounded modern discovery caching and the unchanged transient legacy backend.

The stable packaged skill reads the current workflow and supporting references through
`eplan_get_workflow` on the selected route. Both compatible endpoints also publish the same data
through Skills-over-MCP. [Runtime guidance](docs/runtime-guidance.md) describes explicit live
publication, stale-reference checks and the separate native host reload boundary.

The direct server and optional app-owned framework host report to the existing Windows MCP Service
Manager through framework 0.18.0. No manager installation or broker registration is performed here.
Status uses cached package/plugin metadata and per-instance activity; availability remains unknown
without an update source. Restart stays disabled: EPLAN has no surviving process supervisor or
cross-chat quiescence fence for pending operations and uncertain receipts. New server processes
report automatically; existing chat processes require their normal reconnect to load this integration.
See [service management](docs/service-management.md) for the restart boundary and verification.

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
receipts. Keep organization-specific standards, validation rules and project interpretations in the
corresponding engineering service, using this server's generic source-bound evidence.
Use repository-root `.local/` for private working material; it is ignored by Git and excluded
from release packages. Public examples and fixtures must be synthetic or explicitly redistributable.

## License

[MIT](LICENSE) ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â© 2026 votecoffee. See [NOTICE.md](NOTICE.md) for attribution.
