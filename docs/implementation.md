# Implementation and developer guide

## Architecture and supported profiles

Use [multi-chat readiness](connection-readiness.md) for the current lightweight
metadata/frontdoor design, lazy scarce-work admission and required regression
workload. Per-chat initialization no longer acquires the four legacy heavy
endpoint slots. Old live generations retain their slots until their own exit.

Published direct connections now use the [stable deployment](stable-launcher.md)
contract: retained app-owned engine/runtime, atomic selection, integrity refusal,
peer-preserving updates and exact owner-generation cleanup. A source setup path
or disposable plugin cache is not a published server entry point.

EPLAN owns its standalone SDK 2.3 stdio server, `eplan@eplan-local` plugin and
`eplan-analysis` skill. The shared service layer owns analysis and state changes;
MCP and CLI adapters remain thin callers. Start discovery with `eplan_get_workflow`
and pin returned guide/reference revisions and hashes before using detailed tools.

[CodexMCPBroker](https://github.com/votecoffee/CodexMCPBroker) supplies two distinct
components: the shared Python framework and a separately installed Windows MCP
Service Manager. The manager receives authenticated app-owned status; it does not
replace EPLAN's MCP endpoint, plugin or skills. No universal plugin is required.
The pinned distribution `universal-codex-tools` / import `universal_tools` is a
library dependency, not an installation route. Shared-host/proxy execution is an
optional, unselected profile and is not a prerequisite for standalone use.

| Profile | Behavior |
| --- | --- |
| `direct-standalone-offline` | DXF/PDF, explicit report imports and independent local byte/XML readers |
| `direct-standalone-local-readers` | Adds copy-only ODA DWG/DWT/DWS conversion with explicit executable path and SHA-256 |
| Access/ACE and semantic EPLAN project APIs | Unavailable; no inferred native project API or automatic GUI acquisition |

Selected direct profiles have Windows transport/ownership coverage, including
native ODA cleanup. This does not establish shared-GUI, controller, commissioning
or arbitrary vendor-version acceptance. Package/source checks and actual installed
runtime acceptance remain separate. Historical feature assessments are not live
installation receipts; use selected profile/status and the applicable validation.

## Source installer

`Install.cmd` delegates to `InstallAndRun.cmd`, which selects Python and forwards
quoted arguments to `scripts/launcher.py`. Both are install-only, including the
legacy filename. `--help` performs no setup. The installer verifies the reviewed
framework wheel, installs hash-locked dependencies and this source package into
`.venv`, and creates a default offline configuration only if none exists.

```powershell
.\Install.cmd --framework-wheel "C:\Packages\universal_codex_tools-0.20.0-py3-none-any.whl" --offline
.\.venv\Scripts\python.exe -m eplan_mcp --config .local/config.json serve
```

The default workspace is empty and private; explicit `--root` values are first-setup
only. Existing configuration is preserved. `scripts/install_plugin.py --prepare-only`
with `--stable-root` creates local plugin files without registration or enablement.
The old source setup `--prepare-plugin` flag refuses before installation. Setup does not write global Codex TOML,
install the manager, start a server, or select a native-reader profile. The retained
`--stdio` flag explains the direct run command and fails before installing anything.
No CLI bootstrap wrapper is silently promoted into a native lifetime profile.

`scripts/configure.py` writes only private application JSON. Native configuration
requires a separate explicit profile/executable/hash review; `--oda` cannot activate
it during setup. Failed dependency commands retain their exit code. No shell-built
command string is used by the Python installer.

## Ownership and evidence

The exclusive app entry point applies numerical limits before native-library
imports. Sources are staged as private copies; executable/source identities are
checked around conversion. Workers use literal argv, detached input, bounded
output capture and app-owned nested jobs. Durable reservations precede resume;
retained creation-checked handles authorize cleanup. Preserve pending outcomes and
uncertain write receipts; never infer success or automatically replay effects.

Normal EOF, active/queued cancellation, client/owner loss and native descendants
are distinct checks. A failed observer must not suppress finally-close of its exact
private SDK job. Native owner-crash acceptance still requires descendants gone
before outer job cleanup. Unobserved short-lived job actors are not exact-generation
cleanup proof. See [resource ownership](resource-ownership.md) for implementation
limits and [service management](service-management.md) for honest offline/stopped
states and restart refusal. Do not kill by PID/name or interrupt other sessions.

## TOML publication and Windows newline safety

No public EPLAN path directly writes Codex's global TOML. Plugin preparation writes
local JSON/skill files; automatic global registration remains separate. Use
`scripts.toml_publication.publish_copy` for disposable review copies. It refuses
the live global configuration path before reading/writing it, validates UTF-8 TOML,
checks the expected prior hash, permits only named setting changes, and atomically
publishes bytes. Windows output defaults to explicit CRLF; LF is also selectable.

Never decode existing CRLF bytes, concatenate text, then call Windows `write_text`
with default newline translation: each existing CRLF can become CRCRLF. Normalize
logical newlines once and encode once; use binary writes or `newline=""` for
already normalized bytes/text. Lone CR and CRCRLF input are rejected for review,
not silently repaired. Multiline TOML strings and Unicode must retain parsed values.
No config fixture test should target the user's repaired live file.

## Focused verification and release

Run `tests/test_installer.py` and `tests/test_toml_publication.py` for disposable
Windows CMD forwarding, spaces/Unicode, nonzero exit propagation, real help/error
parsing, LF/CRLF, malformed CR rejection, multiline values, semantic preservation
and stale-copy refusal. The CMD tests use a disposable venv and stub setup; they
do not reinstall the active app. Runtime/worker tests require their separate scope.

Keep private audits, byte samples and runtime receipts under ignored `.local`.
Use one fixed New York timestamp for distributed changes, regenerate the public
byte manifest/source archive, verify wheel RECORDs and commit coherent changes on
`main`. Documentation/source publication does not reinstall or restart a running
profile. See [release procedure](releases.md) and [verification](../VERIFICATION.md).
