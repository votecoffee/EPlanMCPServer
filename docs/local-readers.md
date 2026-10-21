# Independent local readers

The local reader service does not start EPLAN or require its runtime. It copies the selected
source into app-owned scratch storage, verifies SHA-256 before and after, and runs a bounded
worker. Every result identifies the original root, relative path, source hash and file size.
No file edits, database updates, license modifications or EPLAN assembly loading are implemented.

## XML

`eplan_read_xml` discovers exact element tags and counts when record_tag is omitted. Supply
record_tag to read matching nodes with all attributes, text, tail text and nested child structure.
Records include their one-based ordinal among elements with that exact tag. Namespaced tags use
Clark notation. This handles nested parts-management and project-property XML without inventing
canonical mappings. No external references are loaded. DTD/entities and null bytes are rejected.
Limits: 16 MiB input, 100000 nodes, depth 64. Large result fields/pages are explicitly bounded.

Canonical `eplan_import_reports` retains its separate flat-row and explicit mapping contract.
Raw XML extraction does not automatically assert electrical device identity or quantity semantics.

## Access databases

`eplan_read_access` requires Windows, pywin32 and an installed Microsoft ACE OLE DB provider
matching the Python process architecture. Provider installation is an explicit local prerequisite.
The service opens an isolated MDB/ACCDB copy in ADO read-only mode and lists local base tables.
System tables, linked tables and saved queries are excluded. There is no arbitrary SQL input;
only an exact inventoried table name can be selected. Unsupported/encrypted databases report errors.

Read rows with offset/limit. Results preserve column names and ADO type codes, null values,
decimal values as strings, dates as ISO strings and binary values as bounded base64 with hashes.
Row ordinals are provider ordering under a particular source hash, not authenticated primary keys.
Long strings are flagged when truncated. Supply table, exact column and zero-based row offset,
then start/length to read a full cell in slices. Binary cell slices use base64 and byte coordinates;
text cell slices use character coordinates. No memo or binary value is interpreted as executable code.

## Project links and ordinary archives

`eplan_read_project_link` reads BOM-marked UTF-16 or UTF-8 ELK/ELL link text, preserving raw lines.
It recognizes one unambiguous `.edb` reference and version-shaped text. References must remain
relative and within the configured root. Missing template/database folders remain explicit missing
references. EDB directory inventory is not an atomic snapshot of a running project.

`eplan_read_archive` handles ordinary `.zip` files only. It can list entries or read one unique
exact member using the XML, Access, link-text or binary readers. It never trusts member paths;
absolute paths, traversal, symlinks, encrypted members and duplicate names are rejected for reads.
Members are CRC-verified and limited to 64 MiB; the archive inventory is limited to 100000 entries.
Native ZW1/ZW9 backups are not assumed to be ZIP, even if an archive library might recognize one.

## Binary content and compressed streams

`eplan_read_binary_bytes` returns up to 4096 bytes as hex. `eplan_read_binary_text` finds literal
ASCII and ASCII-compatible UTF-16 strings within a selected window of up to 4 MiB. Results carry
encoding, byte offset and byte length. These are candidates: incidental strings, obsolete content
and boundary fragments can appear. Non-ASCII character encodings are not silently guessed.

`eplan_find_compressed_streams` scans at most 4 MiB per request for zlib headers and accepts only
streams that fully decompress with a verified checksum. It tries at most 512 candidate headers per
request and stops after a cumulative output budget; each stream has a 16 MiB inflated-size limit.
The stream scan is non-overlapping and does not recursively decompress embedded streams.
Follow next_scan_byte_offset for window/budget continuation; offset/limit paginate discovered streams
within that scan independently. A stream header at a window boundary is included using look-ahead.

Supply stream_offset to the byte/text reader to inspect inflated content. Results include the
source stream offset, compressed length, inflated size/hash and an explicit coordinate system.
Inflated byte offsets must never be cited as original file offsets. Compression integrity establishes
byte recovery, not knowledge of the EPLAN record schema.

## Experimental EOD slots

`eplan_read_eod_slots` recognizes a repeated binary header pattern and infers fixed-slot geometry
only when at least three pattern matches yield intervals whose greatest common divisor exactly
partitions the file. Alternatively, an analyst may provide explicit slot_size. Up to 100000 slots
are permitted. Unsupported layouts fail with a request to use the raw byte/text tools.

The reader returns slot offsets, raw big-endian header integers, pattern-match flags and bounded
raw text candidates. These integers are not authenticated EPLAN object IDs or type enums. Neither
matching nor missing headers establish whether an object is current, deleted or reused. No property
meaning, drawing geometry, page hierarchy or electrical relationship is inferred.

## CLI

All operations use the same LocalDataService through MCP and the CLI:

```powershell
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json local-read engineering parts.xml xml
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json local-read engineering parts.mdb access
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json local-read engineering example.elk project
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json local-read engineering example.edb/Function.eod streams
```

Use `--options` with a local JSON file for record_tag, table, pagination and byte-window options.
Store customer schemas, extracted records, source manifests and installation evidence in ignored
local storage or the owning engineering service. Public fixtures must remain synthetic.
