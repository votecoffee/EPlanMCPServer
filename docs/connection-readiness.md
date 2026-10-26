# Multi-chat connection readiness

Follow the shared [connection-readiness contract](https://github.com/votecoffee/CodexMCPBroker/blob/main/docs/server-development/connection-readiness.md).
The framework and optional Windows manager are separate products; this design
keeps the standalone SDK 2.3.0 server/plugin and framework 0.20.0 pins. It does not
select an optional shared host or TDQS feature.

## Independent budgets

The expected acceptance workload is six simultaneously connected chats, including
simultaneous cold startup and reconnect. Twelve lightweight metadata leases per
operational state provide bounded headroom. Each is an actual OS byte-range lock
with a native host/PID/creation-time/image identity receipt. Historical `held`
receipts are observations, not slot authority; kernel locks release on exit.

Idle metadata processes do not import NumPy, ezdxf or PyMuPDF, hold analysis leases,
or launch a persistent analysis process. Metadata, current generation guidance,
schemas, capabilities and durable receipt lookup remain available when analysis
is busy. Guidance snapshots are version-specific; old peers keep their guidance.
Operational state, request journals, worker locks and registry remain shared.

Analysis admission is lazy, immediate and at most four per operational state;
`max_concurrent_requests` may narrow that limit. Busy returns an expected tool
error before dispatch. Each accepted call runs in a disposable owned process.
Each frontdoor dispatches one costly call at a time, within the configured upper
bound, so its nested owned tree stays within budget. Parallel chats share the
separate global analysis pool. The existing parser-worker and ODA pools are unchanged and remain shared with old
generations. Per-frontdoor request and queue limits also remain configured.
No legacy endpoint lease or uncertain request is deleted, stolen or replayed.

The serving frontdoor is the surviving owner of the analysis job. All descendants
inherit its kill-on-close job, bounded to twelve processes and 768 MiB job commit.
Count SDK console helpers separately in aggregate observations; they can predate
the app job. Six idle frontdoors must be measured together, with existing peers
reported separately. The configured twelve-frontdoor ceiling is not a claim of
negligible aggregate memory. Twelve owned trees imply an absolute aggregate job
commit ceiling of 9 GiB, plus SDK helpers and unchanged legacy generations.
Normal acceptance measures actual private commit, working set, threads and actor
identities; do not infer commit from a small working set or increase limits to
hide an ownership leak.

Parser units retain their configured timeout. A whole ephemeral analysis call is
bounded to five parser-unit budgets plus thirty seconds. Writes still use the
original durable request journal. EOF/cancellation can leave an unknown write
receipt: inspect its request_id, never infer rollback or resend it. Backend stage
observations are returned on completion; live per-stage progress streaming is not
advertised by the lightweight frontdoor.

## Regression and deployment gates

1. Inventory the exact exhausted pool with kernel file owners and native creation
   identities. Inspect live management activity without acquiring another endpoint.
   A live idle lease is legitimate occupancy, not stale cleanup permission.
2. Compare frontend schemas with the actual pinned backend-generated catalog.
   Check integer bounds, defaults, meaningful busy/validation errors and masking
   of unexpected failures. Regenerate `scripts/generate_tool_catalog.py` after
   choosing the fixed release stamp, then run it with `--check` against the same
   pinned build environment. Catalog generation belongs in source release checks.
3. Exercise the real installed route with six overlapping metadata clients, shared
   analysis pressure, synthetic reads and peer-preserving close/reconnect. Prove
   idle, active and transport-queued EOF without cancelling the tested workload
   before closing its transport. Retain exact owner and child handles through the
   fault and prove descendants gone before outer SDK safety cleanup.
4. Test failed initialization, startup limits, original Unicode wire handles,
   parent loss with a held writer, and exact dead-generation reconciliation.
   Protect unrelated peers, shared/attached software and uncertain journals.
5. Install reviewed immutable bytes and pin the actual saved command/args/cwd/env.
   Windows Store/MSIX can redirect logical AppData into a different physical
   installation. Inspect both views and native image paths. Prefer an explicit
   app-owned installation outside redirected AppData; do not assume updating one
   pointer updates another filesystem view. Never edit a versioned plugin cache.
6. Have the single authorized settings publisher parse the complete proposed TOML
   with production types, preserve unrelated settings/newlines/BOM, perform CAS
   publication and validate readback. A ready binding proposal is not publication.
   Then verify cold saved-route readiness and actual discovery in a reloaded chat.

## Observing the tests

Keep observation jobs separate from the application's owning job. Retain exact
process handles before a deliberate owner fault, observe the entire outer job
empty before its safety handle closes, and record any safety escalation as a
failed acceptance. A Python venv launcher can create a second interpreter process:
the actual transport writer and parent identity must come from native handles,
not an assumption that the initial launcher PID survives as the interpreter.

Close the original stdin pipe to exercise EOF. Closing an SDK memory-stream writer
alone can leave the process pipe open; cancelling the workload first tests a
different event. A retained duplicate writer must not hide exact parent death.

Bound observer overhead and keep its failures fatal. Share expensive system-wide
thread snapshots across simultaneous observers. Measure current aggregate private
commit at the same observation boundary; do not add independent historical job
peaks and label the result a simultaneous peak. Retain per-job peaks separately.
Windows documents the distinction in its
[job memory accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information).
Keep failed observer/writer attempts alongside corrected proofs instead of
rewriting them into successful observations.

Retain source/package, installed selection, fresh protocol, concurrent workload,
host activation and native workflow evidence separately. Offline XML or a tool
declaration does not reaccept native ODA lifecycle, native EPLAN editing, a GUI,
Access/ACE or a controller. Unchanged domain-reader acceptance remains scoped to
its retained artifacts; propose any genuinely needed new heavy native case
separately instead of starting engineering applications during connection repair.
