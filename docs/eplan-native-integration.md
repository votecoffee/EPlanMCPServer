# Native EPLAN integration boundary

Version 0.1.0 is an offline export and drawing analysis server. It does not launch EPLAN,
open projects, restore backups, alter project databases, load SDK assemblies or run arbitrary actions.
ELK, EDB, ZW1/ZW9 and macros are inventory only. Flat XML reports are parsed only with an explicit
row element and property map; generic XML parsing is not a native EPJ reader.

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

No EPLAN installation was discovered in the standard Program Files folders during initial setup.
That is limited discovery, not proof that no installation exists elsewhere.
