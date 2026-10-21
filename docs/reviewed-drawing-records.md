# Reviewed drawing records

Use this workflow when a reviewer has established an explicit device fact or connection in a PDF
and needs to query it through the same profile and supply tools as declared reports. The server
checks source hashes and quoted text. The reviewer remains responsible for the interpretation:
matching text does not prove an assignment, connection, direction, pressure or operating state.

## Import

1. Index the PDFs using the configured drawing root. Keep originals unchanged.
2. Review the complete relevant pages, labels, tables and cross-references. Retain uncertainty;
   never turn nearby text, repeated names or geometry alone into a supply link.
3. Write flat CSV/JSON/XML report rows under a configured private report root, using the existing
   canonical fields and report kinds. Keep each drawing revision separate unless explicitly reconciled.
4. For each report, write a JSON evidence sidecar and add `evidence_relative_path` to its declaration.
5. Import using `eplan_import_reports`, then query the immutable snapshot. Inspect freshness of
   the reports, sidecars and original PDFs on every response.

Example declaration:

```json
{
  "relative_path": "reviewed-devices.json",
  "kind": "devices",
  "evidence_relative_path": "reviewed-devices.evidence.json"
}
```

The report could contain `[{"tag":"D1","description":"Inspection camera"}]`. Its sidecar has
this structure. Replace the zero hash with the actual PDF SHA-256 returned by the drawing tools:

```json
{
  "schema": "eplan-row-evidence/1",
  "rows": [
    {
      "row": 1,
      "reviewer": "Reviewer label",
      "note": "Device tag and description checked on the page. Supply remains unresolved.",
      "references": [
        {
          "root_id": "drawings",
          "relative_path": "device-schematic.pdf",
          "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
          "page": 1,
          "quotes": ["D1 inspection camera"]
        }
      ]
    }
  ]
}
```

Paths are relative to configured roots. The sidecar uses the report's root; each PDF reference names
its own root. JSON and XML report row ordinals start at 1. For CSV/TSV/TXT, the header counts as 1
and data records start at 2, including when one data record contains embedded newlines.
Every report row must have exactly one sidecar entry. Duplicate, missing and extra entries fail.

Each quote must match a complete extracted text record on the indicated page. Whitespace is folded;
case is preserved. Substrings and text assembled across records are not accepted. Use separate quotes
for separate text records. If the text occurs multiple times, all matching record indices and bounding
boxes are retained; the service does not silently select a nearby occurrence.

## Evidence and freshness

Imported rows, device facts, path edges and supply records carry `evidence: reviewed_drawing_assertion`,
the reviewer label/note and original PDF references. The server adds source-derived record indices
and bounding boxes. `reviewer_authenticated` and `native_engine_validated` remain false. A reviewer
label is an attribution supplied by the caller, not a signature or an approval authority.

The immutable snapshot binds the report, sidecar and every cited PDF. All are checked again before
publication. Changed or unavailable PDFs remain explicit in later freshness results; the historical
claims remain readable. No native project is opened and no source file is modified.

Hash and quote checks prove only that the cited extracted text was present in the specified bytes.
They do not verify that the interpretation follows from it, establish physical continuity, choose the
governing revision or prove live state. A resolved supply trace covers only the supplied relationships.
Do not invent missing device ports or internal bridges merely to complete a path. A pneumatic sheet
reference without known connector/port identifiers can remain a reviewed note instead of a trace edge.

Sidecars are limited to 4 MiB and 2,000 reviewed rows. Each row accepts 1-8 PDF references, each with
1-20 quotes up to 1,000 characters. A quote may match up to 100 text records on its page. One import
accepts at most 128 distinct drawing references. Current extraction caches are required; raster-only
pages without matching embedded text cannot be bound through this workflow.

Snapshot comparison compares canonical engineering fields and their multiplicities. A changed review
note or reference changes the snapshot identifier, but is not reported as an engineering-field change.
