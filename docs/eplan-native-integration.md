# Native EPLAN integration boundary

Version 0.2.0 provides independent offline data readers in addition to export and drawing
analysis. It does not launch EPLAN, open native projects, restore backups, alter project databases,
load SDK assemblies or run arbitrary actions. Nested XML, Access tables, project-link text and
raw/decompressed binary evidence are independently readable. Experimental EOD slots expose raw
headers only. Native lifecycle state, property schemas, geometry and connectivity are not decoded.
ZW1/ZW9 and macros remain inventory only; native backup extensions are never assumed to be ZIP.
See [local readers](local-readers.md) for exact limits and provenance.

EPLAN's official [project API](https://eplan.help/en-us/Infoportal/Content/api/2026/CreateOpenProject.html)
requires a project to be open in EPLAN for DataModel access, and an offline program must use
a LockingStep. The official [export action](https://eplan.help/en-us/Infoportal/Content/api/2025/export.html)
documents PDFPROJECTSCHEME, DXFPROJECT, DWGPROJECT and PXFPROJECT (EPJ). Exporting connections
with PXFPROJECT requires EXPORTCONNECTIONS; its default is off. A report can therefore be incomplete
even when parsing succeeds. No export scheme or vendor property ID is assumed by this server.

A future native adapter needs app-owned testing against the installed EPLAN version and license,
an explicit project selection, reviewed action/parameter allowlists, source preservation on copies,
bounded operations, durable receipts, and post-operation readback. Package tests do not establish
native acceptance. No such adapter is claimed by this release.
