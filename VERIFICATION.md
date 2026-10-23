# Verification

## Source-only checks

Run from a development environment with the reviewed framework wheel and test tools:

```powershell
python -m pytest -q tests/test_installer.py tests/test_toml_publication.py tests/test_package.py tests/test_offline_profile.py tests/test_local_reader_candidate.py tests/test_native_threads.py tests/test_release_version.py
python -m ruff check scripts tests src
python scripts/stamp_release.py --verify
python scripts/package.py --output .local/packages/RELEASE/EPlanMCPServer-source.zip
python scripts/package.py --verify
```

Source packaging uses an explicit allowlist, license and exact byte manifest. Keep
outputs private. Compare wheel METADATA, RECORD payloads and display/canonical
versions. Building a package does not install, enable or restart the running app.

Installer tests use a disposable path with spaces/Unicode and a disposable venv.
They exercise actual Windows CMD forwarding, exit code 37 propagation, real
help/invalid-argument parsing and an inert install command plan. They do not
install dependencies into the active app, register plugins or start a server.

TOML tests publish only disposable UTF-8 files. Cover LF/CRLF input and output,
Unicode, multiline strings, parsed settings, unrelated-setting preservation,
malformed CR/CRCRLF rejection, stale hashes and refusal of the protected live
target. Windows text translation can turn existing CRLF into CRCRLF. The safe
writer normalizes once, encodes once and publishes bytes.

## Selected runtime profiles

The direct offline profile covers PDF/DXF, explicit reports and provider-free
XML/link/archive/byte readers. The explicit local-reader profile additionally
uses a reviewed SHA-pinned ODA converter against staged DWG/DWT/DWS copies.
Access/ACE dispatch and semantic native EPLAN project APIs remain unavailable.

Selected Windows direct-profile validation includes initialize/current guidance,
50 tools, source-preserving reads, authenticated healthy idle management, restart
refusal, normal/active/queued EOF, cancellation, independent sessions, client loss
with held writer, supervisor crash, ODA descendants gone before SDK cleanup,
revision-bound orphan/idempotent receipts and unrelated harmless stand-ins.

Runtime, package bytes, plugin/cache route and host activation are separate
evidence layers. Repeat applicable checks for a changed implementation or runtime.
No native test, normal reinstall, restart or config activation is implied by a
docs/source checkpoint. Never use customer projects or existing editors as
cleanup fixtures. Preserve raw failures as failures.

## Ownership and uncertainty

Record source/executable/cache/preview hashes, creation-bound handles, private job
accounting and terminal claims. Intermediate DXF bytes are not retained by the
selected API; do not invent their hash or race a live converter file to obtain one.
Finally-close must still attempt the exact SDK job cleanup if an observer fails,
preserving the original error afterward. Abort cleanup is not a native acceptance
pass. Deliberate native owner-loss acceptance requires descendants gone before
outer cleanup.

An unobserved short-lived job PID is not exact-generation cleanup proof. Keep
whole-job accounting/emptiness distinct from retained handles; never adopt,
reopen or kill a PID to fill an observation gap. No name-based cleanup or
history-wide quiescence is allowed.

Cancellation is not rollback. Preserve unknown requests/barriers and inspect
effects instead of replaying writes. Manager offline/stopped state, plugin-version
unknown and update availability remain honest. Automatic restart, shared GUI,
HTTP/shared-host ownership and controller/SCM access are separate boundaries.

See [implementation](docs/implementation.md), [ownership](docs/resource-ownership.md),
[management](docs/service-management.md) and [guidance](docs/runtime-guidance.md).
