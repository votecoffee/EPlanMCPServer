# Repository guidance

- Preserve source projects, exports and drawings. Never open or save native projects automatically.
- Keep customer data, private paths, runtime state and evidence under ignored `.local/` or outside this checkout.
- Put operations in the shared service layer; CLI and MCP are thin adapters.
- Separate EPLAN export assertions, CAD observations and PDF candidates. Never infer electrical continuity from text or geometry alone.
- Independent readers may inspect verified ELK/ELL link text, XML, Access and raw/decompressed binary evidence on copies. Semantic native project access requires separate verification. Never assume native databases or ZW1/ZW9 are ordinary XML/ZIP files.
- Work on main; make focused commits and push after relevant checks pass, as explicitly authorized by the user.
- Test source preservation, malformed inputs, path boundaries, source freshness, concurrency and real MCP transport.
- Include license and byte manifest in source packages. Use LF endings. Do not publish customer evidence.

- Keep public documentation reusable: no machine-specific setup receipts, customer paths or usage history. Put these under repository-root `.local/private-docs/` or outside the checkout.
- Keep the root README aligned with Standard Readme, including Table of Contents, Install/Dependencies, Usage/CLI, Contributing and License.
- Keep application features vendor-generic. Organization-specific standards, rules, station mappings and engineering interpretations belong to the corresponding engineering service, using generic source-bound evidence from this server.
