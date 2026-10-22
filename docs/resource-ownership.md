# Owned resource lifecycle

This remains unaccepted for MCP/native-host use. Pure/stub checks and bounded harmless Python
process fixtures cover selected ownership paths, not transport/native acceptance.
No plugin/server/native application is started by validation
while an operator runtime hold is active. Existing native editors and unrelated processes are
never enumerated, adopted or closed.

## Exclusive ownership

The application CLI enters an exclusive process-owner scope. A library embedded in another
application cannot implicitly adopt that host process. Child launch requires that exclusive scope
and a private evidence directory selected by the application configuration. Enabled launch sites
cover extraction, preview, table and local-reader Python workers. ODA, Access providers, plugin
CLI installation/inventory, shared hosts and HTTP are unavailable from selected entry points.
All child arguments are literal argv, with no shell command expansion. There is no native EPLAN
editor attachment, shared application lease or dirty native project save/close operation.

Before creating children, the exclusive app process is assigned to a private Windows job with
kill-on-close and a 64-process limit. Its non-inherited job handle is retained until OS process exit;
it is not explicitly closed during an orderly close because that would terminate the owner itself.
Children inherit job membership from creation. This protects the otherwise vulnerable interval
between child creation and explicit assignment to its nested job.

Each root child is created suspended and assigned to a separate private kill-on-close job before
the primary thread resumes. Retained process and primary-thread handles bind creation/cleanup;
diagnostic PIDs are never reopened for termination. Each child tree has a 16-process limit, and an
owner admits at most 16 active trees. These containment limits do not establish a memory budget.
Breakaway is not requested. Nested-job refusal fails closed without running the suspended child.
Descendant shell/Node/console processes stay within their exclusive tree; no name-based global
cleanup is used. The implementation uses CPython's Windows creation primitive and pywin32, so
runtime/version compatibility and nested-job behavior still require native acceptance.

Normal child completion terminates residual descendants and waits for an empty job. Startup
failure, timeout, cancellation and owner-scope exit also request teardown through retained handles.
The request scheduler propagates a cancellation event to owned workers and drains their cleanup
before releasing admission. This does not roll back earlier files in an indexing batch or clear
an unknown write receipt. Output is detached from MCP stdin/stdout, spooled to private temporary
files and checked against a 4 MiB capture budget. Polling is not a hard disk quota.

## Durable evidence and recovery boundary

Every explicitly launched root tree has a versioned private JSON record under the selected state
directory's `owned-resources/`. Before resume, the record retains owner/resource UUIDs, owner and
child creation times, diagnostic PIDs, exclusive ownership, containment type and lifecycle state.
Arguments and source paths are omitted. Records use flushed/fsynced temporary files and atomic
replacement. Nested worker launches inherit only the private evidence location, not permission to
adopt another app. These are tree ownership records; individual short-lived descendant events
are not a complete process audit trail.

Interrupted records survive owner death. A recorded PID or an old `running` state does not prove
present ownership. There is no automatic replay, stale-PID killing, journal clearing or recovery
mutation. Cleanup uncertainty refuses success and fences further child launches in that owner.
Review the retained resource record together with the app request receipt and source hashes before
further engineering work. Inaccessible evidence prevents launch; no unjournaled fallback exists.

Framework 0.20.0 `ResourceLedger`/`ResourceOwner` are integrated at source level. They use the same
explicit `EPLAN_MANAGEMENT_REGISTRY` as service reporting, or the framework's default private
registry. The actual launching supervisor creates its own generation. Before creation the shared
ledger reserves a private, termination-eligible `offline-worker` claim. Before resume, its host
identity, PID, decimal creation FILETIME and normalized executable image are compared against the
retained creation handle. The app journal links to the shared resource ID.

The app retains its stream/capture containment instead of using the framework background launcher,
which does not provide inherited MCP stdio. Shared records declare `app_owned` containment: the
manager may review an exact-process orphan, but does not acquire the app's job or infer a complete
descendant inventory. EPLAN owns job/tree teardown. Confirmed teardown is reconciled through the
shared API after exit verification; unverified cleanup records a recovery barrier. Existing
barriers and cleanup receipts are never cleared automatically. Interrupted launch reservations
remain visible. Shared records bound non-retired EPLAN claims to 32 across supervisor generations.

Manager recovery remains a reviewed operation with exact host/identity, ownership, revision,
conflicting-claim and uncertainty gates. No prior app-only JSON is silently imported or adopted.
Neither the adapter nor status reads perform orphan cleanup or migrate a live registration. Real
cross-manager recovery, transport and native cleanup acceptance remain pending.

Optional framework serve/proxy entry points are blocked until their backend containment and
shared-owner lease profile is accepted. Bootstrap and plugin-install wrappers are likewise blocked
until their separate ownership profile is ready. Publication/preparation of local data does not
enable or restart those routes. Non-Windows child execution has no unmanaged fallback.

## Status and acceptance

### Launch-path coverage

| Path | Ownership and containment | Source gate / remaining acceptance |
| --- | --- | --- |
| Direct stdio / loopback supervisor | Actual exclusive Python process owns its workers; no registration helper acts as owner | Implemented; existing SDK transport retained; new EOF/reconnect/crash/resource-use acceptance pending |
| Extraction / local-reader / render / table worker | Shared ledger reservation, retained creation handle, app-owned Windows job tree | Pure/stub checks pass; real creation, descendants, cancellation and owner death pending |
| ODA converter | No discovery; configuration and conversion refused | Disabled; no vendor process launch in this profile |
| Access provider objects | Direct/archive/worker Access dispatch refused; MDB bytes remain readable | Disabled; no COM/provider acquisition in this profile |
| Shell / Node / console descendants | Job contains descendants of a directly launched private process; no arbitrary shell expansion | Real descendant fixtures pending; out-of-job service/COM launchers are not supported or adopted |
| Existing user-owned native editor | Not opened, attached, enumerated or closed | Protected by absence of acquisition; attached preservation fixture still pending |
| Shared native application / optional framework host | No accepted lease/refcount or backend containment profile | Implementation gap; serve/proxy startup refused, no automatic host start |
| Bootstrap / plugin installer wrappers | No accepted dependency-free installer containment profile | Implementation gap; entry points refuse installation/startup |
| Windows manager recovery | Shared record host/creation/image identity and explicit private policy; no app auto-cleanup | Shared API stub integration checked; real orphan/receipt/barrier recovery pending |

The direct offline profile is the candidate for controlled runtime validation. An unsupported
optional launch path does not become enabled when a transport test passes. Start/close ownership,
real manager recovery and supported Python/Windows containment must pass before ordinary use.
Abrupt upstream-client loss with inherited open pipe handles is not established by source review;
client EOF, parent/owner termination and duplicate reconnect need separate transport fixtures.
No native dirty-document policy is implemented because native editor/project access is unsupported.
Engineering write uncertainty remains in existing request journals; no journal replay or barrier
resolution is performed by the ownership adapter.

`eplan_concurrency_status.resource_ownership` reports bounded process-local ownership observations.
Service-manager status reports the active owned-tree count and that acceptance is pending; it does
not scan native applications or claim access to every resource record from other processes.

Pure OS-stub tests check containment-before-resume ordering, persisted creation identity, startup
failure, cancellation, timeout, bounded admission, cleanup failure, and continued cleanup after one
resource fails. No real process is launched by these tests. Subsequent isolated acceptance must prove:

- Direct child and descendant cleanup on normal completion, client EOF, timeout and cancellation.
- Abrupt owner death during creation/assignment/resume and active worker/converter execution.
- Startup/assignment refusal, nested jobs, handle inheritance and capture cleanup on supported Windows/Python versions.
- Preservation of independently launched or attached applications and another owner's shared resources.
- Durable crash records, identity mismatch/PID reuse rejection, cleanup uncertainty and shared-ledger migration.
- Real direct transport, packaged runtime and full regression after the lifecycle changes.

Run those checks only after explicit release of the runtime hold. Never use an engineering project
or user-owned native application as a cleanup fixture.
