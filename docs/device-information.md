# Device information

The primary output is a source-bound device profile: names/descriptions, IP addresses, PLC I/O
points and the electrical or pneumatic supplies feeding the device. Raw file access supports this
goal; discovering strings alone is not a semantic device model.

## Structured records

Use `eplan_import_reports` with explicitly mapped records. The device tools join exact tag strings
and retain source hashes, row references and conflicting claims. Scope can be selected with
installation/location; known duplicate tag scopes are never silently combined. Part catalogs describe
available parts and do not establish which devices are installed or how they are connected.

For explicitly reviewed PDF claims, use an `evidence_relative_path` sidecar as described in
[Reviewed drawing records](reviewed-drawing-records.md). Profiles, facts and supply paths retain that
distinct evidence label, reviewer note and checked quotes; freshness includes the original PDFs.

`eplan_get_device_profile` returns:

- Device names, descriptions, manufacturer and part numbers when explicitly reported.
- IP/interface/port facts, including literal validation and potential same-context conflicts.
- PLC/controller, rack, slot, channel, address and signal facts. Multiple I/O points on a device
  remain separate facts and are not treated as a conflict merely because addresses differ.
- Electrical and pneumatic supply summaries, with ratings retained as declared text and units.
- Associated source records with pagination. The first ten facts per field are returned alongside
  full counts; use `eplan_query_export` for additional underlying records.

## Supply records and paths

Additional report kinds:

| Kind | Meaning |
| --- | --- |
| `supplies` | Declared source devices/output ports, medium and optional ratings |
| `supply_links` | Declared upstream-to-downstream terminal relationships |
| `supply_references` | Device-associated feed labels/sheet references with unresolved port connectivity; never graph edges |
| `bridges` | Explicit terminal/device-internal transfer relationships |

Relevant canonical fields are `tag`, `terminal`, `medium`, `supply_kind`, `voltage`, `voltage_unit`,
`pressure`, `pressure_unit`, `source_tag`, `source_terminal`, `target_tag`, `target_terminal`,
`flow_direction`, `source_installation`, `source_location`, `target_installation`, `target_location`.
Medium must explicitly identify `electrical` or `pneumatic` for supply tracing. Other values remain
raw records and are not interpreted by this tracer.

For a known feed reference with missing port details, import `supply_references` using the downstream
device `tag`, `medium`, `source_reference`, `target_reference` and optional `description` and scope.
Use an evidence sidecar for reviewed PDF references. Profiles and supply traces return these under
`reported_references`, retaining notes, PDF quotes and source hashes. Only the first ten are included
with counts; use `eplan_query_export` with kind `supply_references` for further records.

These references do not create nodes or edges, resolve a path, or become device descriptions or
pressure/voltage facts. Even if the source reference names a supply, port connectivity remains
unresolved until explicit terminal relationships are supplied. Do not fabricate ports to satisfy the tracer.

`eplan_trace_device_supply` starts at the selected device/terminal and follows upstream declarations.
`supply_links` declare source-to-target flow by kind. Ordinary `connections` and `bridges` require
explicit flow_direction: `source_to_target`, `target_to_source` or `bidirectional`. A plain from/to
export can describe arbitrary reference orientation, so it does not automatically establish feed flow.

Internal conduction is never assumed between a fuse's terminals, terminal-strip positions, relay
contacts, valve ports or other device terminals. Add a bridge only when a supplied record explicitly
establishes that transfer. A static declaration does not prove the current switch/valve state.

Paths retain every relationship's row/hash. Branching supplies remain separate. Missing bridges,
unknown direction, missing source ports, ambiguous scopes, cycles and traversal budgets remain
explicit. `complete_for_supplied_relationships` describes only the supplied records; it does not
establish project-wide coverage, current energization or physical continuity. Inspect source freshness.

## Drawing evidence

`eplan_collect_device_evidence` identifies validated IPv4 literals, power/air labels and common
I/Q address-shaped text and bracketed DI/DO, AI/AO, GI/GO and UI/UO literals in extracted drawing text.
For example, `DO[101]` remains a literal candidate; it does not establish a controller, manifold,
valve, signal direction or device assignment. The same literal on separate records/pages remains
separate evidence. Supply a literal device_query to collect matching
text and nearby PDF lines within a bounded radius on the same page. Results include source hashes,
page/bounding box or CAD text locations, anchor record references and candidate counts by category.

Air candidates include plant air, air feed/preparation/manifold/drop/lockout and dump-valve labels,
as well as pressure text. These labels locate evidence for review; they do not establish an air
path, a valve state, an installed pressure or an association with nearby actuators.

This stage deliberately does not assign a nearby IP, PLC address or supply to the device. Repeated
title blocks, revision notes, catalog descriptions and adjacent circuits can contain unrelated matches.
Address-shaped text can be a false positive. Candidate counts are text occurrences, not unique devices
or unique addresses. Raster-only content and unsupported entities remain coverage gaps.

Index drawings first. To investigate a particular label, combine the candidates with positioned text,
tables, drawing previews and explicit report relationships. Promote a claim only after its source
actually establishes the association; never convert proximity into an electrical/pneumatic edge.

## Synthetic example

Configure `examples/device-profile` as root `demo`, then import its `reports.json` declarations.
The example describes one camera, one IP, two PLC I/O points, a 24 VDC source via an explicitly
bridged terminal strip, and a 5.5 bar air source. These are synthetic assertions, not customer data.

```powershell
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json import-reports demo examples/device-profile/reports.json
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json device-profile ep_HASH D1
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json supply-trace ep_HASH D1 --medium electrical --terminal PWR
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json supply-trace ep_HASH D1 --medium pneumatic --terminal AIR
```

Replace ep_HASH with the returned snapshot_id. Historical snapshots without the new report kinds
remain readable; missing collections are queried as empty rather than rewriting historical evidence.

PDF table results include a cell_bboxes matrix aligned with cells. Coordinates are PDF points on the reported one-based page; merged or absent cells can be null. Use the cell boundaries and page preview to review explicit row assignments. Table detection remains heuristic, and switch-port text does not establish electrical or pneumatic continuity.
