# Repository guidance

- Preserve source projects, exports and drawings. Never open or save native projects automatically.
- Keep customer data, private paths, runtime state and evidence under ignored `.local/` or outside this checkout.
- Put operations in the shared service layer; CLI and MCP are thin adapters.
- Separate EPLAN export assertions, CAD observations and PDF candidates. Never infer electrical continuity from text or geometry alone.
- ELK/EDB/ZW1 require a separately verified native EPLAN integration. Never decode them as ordinary XML or ZIP files.
- Work on main; make focused commits and push after relevant checks pass, as explicitly authorized by the user.
- Test source preservation, malformed inputs, path boundaries, source freshness, concurrency and real MCP transport.
- Include license and byte manifest in source packages. Use LF endings. Do not publish customer evidence.
