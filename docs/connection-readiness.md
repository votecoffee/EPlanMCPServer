# Multi-chat connection readiness

Follow the shared [connection-readiness contract](https://github.com/votecoffee/CodexMCPBroker/blob/main/docs/server-development/connection-readiness.md).
The framework and optional Windows manager are separate products; this design
keeps the standalone SDK 2.3.0 server/plugin and framework 0.20.0 pins. It does not
select an optional shared host or TDQS feature.

## Independent budgets

The deployment workload must be measured rather than inferred from a small pilot.
The selected acceptance budget is sixteen ordinary connected chats, two additional
loaded chats and two overlapping reconnect/review connections. Twenty lightweight
metadata leases per operational state cover that finite demand. More demand is
refused explicitly; this is not unlimited many-chat availability. Each lease is an actual OS byte-range lock
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
An inner job limits the metadata process to 128 MiB and one actor. Child creation
silently leaves only this inner job and stops at the non-breakaway outer owner
job. Analysis descendants remain in that outer full-tree job; no child escapes
containment. See Microsoft's [nested-job inheritance rules](https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs).
Retain actual process/job membership proof when changing this topology.

For `M` metadata processes and `A` admitted analysis trees the new app's kernel
ceilings are `M + 11*A` actors and `(M-A)*128 + A*768` MiB private commit. With
one configured analysis slot this is 27 actors/2688 MiB for sixteen chats and
31 actors/3200 MiB at twenty-client reconnect capacity. With four analysis slots
the twenty-client ceiling is 64 actors/5120 MiB. Admission remains at most four;
parser and ODA pools may narrow actual parallelism further.

Count SDK console helpers separately; they can predate the app job. Measure their
actual count and commit. Do not label these app-owned ceilings as host-wide
limits. Existing legacy generations retain their own original limits. In
particular, an old generation without a memory limit cannot acquire a finite
transition memory ceiling through observation alone. Report new-generation hard
bounds plus the independently measured legacy overlap, and state that limitation
until those peers close naturally. Never terminate them to make a budget pass.

Validate simultaneous cold admission at the intended demand and actual reconnect
peak, metadata at analysis capacity, and one further meaningful refusal. Keep
the earlier six-client pilot under its original scope; it is not evidence that
twenty clients were tested. Report normal and transition processes/private commit.
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
