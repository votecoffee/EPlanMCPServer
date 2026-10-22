# Runtime guidance and skills

The standalone plugin keeps the focused `eplan-analysis` name/description and a short stable
bootstrap. Generate that packaged file from `guidance.py` with `python scripts/generate_skill.py`.
Maintain detailed workflow text in `guidance.py` and supporting references under
`src/eplan_mcp/references/`. The former docs paths are navigation links, not maintained copies.

## Ordinary tool reads

Both direct and app-owned framework backend profiles expose `eplan_get_workflow`. Call without
arguments for the current guide and reference catalog. Returned identity, workflow revision,
instruction SHA-256, skill-catalog revision and reference descriptors bind the complete publication.
Read only needed references using their returned `expected_revision`, `reference_id` and
`expected_sha256`. Stale pins fail; rediscover instead of silently substituting newer content.

Keep the selected route. On the direct endpoint discover the tool schema normally; on the framework
endpoint search/describe `drawing-engine/eplan_get_workflow` and use the described read channel and
catalog revision. Discover/describe engineering tool schemas separately before use. Guidance never
authorizes writes, switches routes, clears receipts or widens policy.

## Skills-over-MCP

The direct SDK 2.3 endpoint uses framework 0.18 `ExtensionServer` and a nonempty `SkillCatalog`.
The optional app-owned host uses `host.create_server(skills=catalog)`. Both advertise
`io.modelcontextprotocol/skills` with real `skills/list`, `skills/get` and `resources/read` handlers.
Directory reads are deliberately not advertised. No Tasks, OAuth, Apps or contributed code is loaded.

The catalog contains one app-owned skill. Its immutable manifest includes the generated bootstrap,
`workflow.md` and supporting references, with exact UTF-8 byte sizes and SHA-256 digests. Resource
content and ordinary tool reads derive from the same publication. Supporting references can be
added/updated/removed atomically; this app does not discover arbitrary contributed skill directories.
Standard extension identity remains fixed for a server lifetime. Framework `broker://skills` reports
the catalog generation/revision; that resource does not imply use of a universal broker.

## Explicit publication

First obtain the current workflow revision from the selected running app. After installing/reviewing
the maintained app guidance, publish locally against the same app configuration:

```powershell
python -m eplan_mcp --config .local/config.json guidance-publish --expected-revision CURRENT_REVISION
```

This local administrative action publishes only the installed app's maintained data. It is not an
MCP engineering write tool. A cross-process lock and expected revision prevent lost updates. A
complete validated immutable snapshot is staged before an atomic pointer change; failed validation
retains the previous publication. Connected clients adopt that pointer on their next request,
using `catalog.publish(..., expected_revision=...)`. Guide/catalog/resource views remain bound to
explicit revisions; hashes indicate content consistency, not authorization or engineering truth.

Source-file edits alone do not modify a publication or an already-running Python worker. Guide data
publication can update connected readers without restarting the service. Engineering implementation
or tool-schema changes still require normal process replacement; the framework profile additionally
requires a new immutable backend publication and an authorized refresh after receipt checks. No
other chat or unresolved-operation barrier is bypassed. State and private publication files are
excluded from public packages.

## Host boundary

Protocol publication is not native Codex skill activation. Official OpenAI documentation describes
[MCP skill imports as plugin-submission snapshots](https://developers.openai.com/plugins/build/skills#import-a-skill-from-mcp),
not runtime fetching by ChatGPT/Codex's native skill loader. Packaged metadata/bootstrap updates can
still require a normal host reload. The practical path after that initial update is the stable
bootstrap plus ordinary live tool reads. Connected-client protocol tests do not verify native host
selection/reload, plugin-submission import or UI activation.
