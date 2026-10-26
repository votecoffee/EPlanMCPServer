# Packed runtime preparation

This source-only facility reduces repeated Python source-file opens while preserving
every selected logical payload hash. It is not wired into the stable launcher,
does not migrate an installed generation, and never starts MCP or a management
endpoint. A changed production bootstrap/layout needs its own reviewed release.

## Prepare a new layout

Run from a development checkout with its dependencies installed:

```powershell
python -m scripts.packed_layout --source C:\EplanRuntime\expanded --inventory C:\EplanRuntime\expanded\inventory.json --destination C:\EplanRuntime\prepared
```

The source inventory must match exactly. The destination must not already exist or
overlap the source. Originals and existing installation selections are preserved.
The result contains `layout.json`, `sources.index.json`, deterministic ZIP_STORED
`sources.pack`, and the unchanged expanded payloads. The returned manifest hash is
the trust anchor; a verifier must receive that exact independently reviewed hash.

The initial reviewed family list is explicit: `annotated_types`, `typing_inspection`,
`mcp`, `mcp_types`, `anyio`, and `universal_tools`. Only their `.py` sources are packed.
Their pinned source uses no direct reads of its own source path. AnyIO's source
inspection uses loader source access; the loader implements it. Universal Tools'
adjacent manager assets remain expanded. Importlib resource reads, including packed
sources, use the same verified logical inventory. Native families, EPLAN's own
source/resources, distributions/metadata and other data remain expanded. This
conservative partition is partial coverage, not a promised cold-capacity cure.

## Verify and consume

`PackedRuntime(root, manifest_hash)` pins original Windows directory and file
generations before reads. It refuses reparse points, hard links, foreign owners or
writers, descriptor drift, unexpected files/directories, missing/duplicate/case-aliased
members, traversal and incorrect logical/physical hashes. It hashes the whole mapped
container AND every original source member, and individually hashes all expanded
payloads. No mtime cache or loose-source fallback is used.

`EngineClosure(engine_root, inventory_hash)` fully hashes and retains the unchanged
engine inventory. Only after both closures verify may `install_finder(engine)` install
the consuming source/native/resource loaders. It limits Python search providers to
the selected runtime/engine; unindexed modules of selected providers cannot fall
through to new loose files. It does not execute `.pth`; supported native aliases are
explicit. DLL search excludes PATH/current-directory providers, retaining selected
native directories and trusted Windows System32. Native imports still use CPython
and Windows' loaders; no claim is made about arbitrary same-process malicious code,
unreviewed dynamic native providers or pre-verifier CPython bootstrap acceptance.

Keep both closure objects alive for the terminal process lifetime. File sharing denies
write/delete; ancestor leases deny directory deletion/replacement. Reads/hash/mapping
use the original retained file object. Mapping uses a temporary FILE handle duplicate,
never an SDK job duplicate. Security descriptors are compared from original handles;
no ACLs are repaired. Each resource/source read checks its retained sharing/descriptor
closure again. This is not a hot-reload/unload API. `close()` is terminal teardown only;
Windows DLL default-search policy intentionally stays restricted until process exit.

## Validation boundaries

Pure tests exercise deterministic bytes, exact logical union, consuming source/resource
access, tamper/index/path/member refusal, native-family exclusions and no loose fallback.
Separate bounded Windows evidence is required for actual sharing/ancestor replacement,
descriptor refusal and a full dependency/import/tool-definition closure. A source test
with a fake lease does not establish Windows sharing. Bootstrap modules already loaded
by CPython remain an explicit trust boundary. No startup-time claim follows from warm
filesystem measurements. All selected bytes are still verified before any prepared
runtime import, and existing expanded launchers/configuration remain unchanged.
