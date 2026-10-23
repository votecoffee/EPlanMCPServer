# Owned resource lifecycle

The selected direct stdio profiles have synthetic/Windows lifetime coverage, including
configured ODA read/preview and native descendants after supervisor loss. Offline,
native-reader and optional host/shared-GUI acceptance remain distinct. Repeat the
applicable checks after changing runtime/vendor bytes. Existing editors and unrelated
processes are never adopted or closed. See [implementation](implementation.md).

## Exclusive ownership

The application CLI enters an exclusive process-owner scope. A library embedded in another
application cannot implicitly adopt that host process. Child launch requires that exclusive scope
and a private evidence directory selected by the application configuration. Enabled launch sites
cover extraction, preview, table and local-reader Python workers. ODA requires the
explicit local-reader profile and pinned executable hash. Access providers, shared
hosts and HTTP remain unavailable from selected entry points.
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
runtime/version changes require renewed containment verification.

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
Neither the adapter nor status reads perform orphan cleanup or migrate a live registration.
Selected direct transport/native cleanup and reviewed orphan receipts have coverage;
shared-GUI leases and automatic recovery remain separate.

Optional framework serve/proxy entry points are blocked until their backend containment and
shared-owner lease profile is accepted. Setup is installation-only and does not start
servers/native apps or activate plugins. Automatic plugin registration remains separate.
Publication/preparation of local data does not
enable or restart those routes. Non-Windows child execution has no unmanaged fallback.

## Status and acceptance

### Numerical pool policy

Before application or worker imports, the exclusive standalone entry point applies a fixed target
of one numerical thread via `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`,
`BLIS_NUM_THREADS`, `NUMEXPR_NUM_THREADS` and `VECLIB_MAXIMUM_THREADS`. Inherited larger settings
are overridden only inside that process. A process that already loaded NumPy/scipy/ezdxf is
refused rather than silently retuned. There is no system-wide environment change or runtime
retuning of another application's libraries. SDK/management/I/O threads still exist; this is not
a claim of one total OS thread or a hard RSS quota.

Service status reports whether the pre-import policy ran and its configured values; it does not
pretend to introspect every native backend's live pool. Pure module-map/environment tests and
isolated dependency diagnostics support the design. Changed application bytes need independent
review and a fresh approved runtime canary measuring startup, active-worker aggregate private
commit, repeated bounded reads, threads/instances and post-cleanup identity state. Prior lifecycle
evidence from an older immutable wheel is not automatic acceptance of this startup change.

### Launch-path coverage

Direct stdio, worker cancellation, client/supervisor loss and configured ODA
conversion have selected Windows lifetime coverage. Those results do not acquire
native editors or shared applications. Access/ACE, HTTP and optional shared-host
profiles remain unselected. Setup is install-only and never starts a native app
or activates a plugin. See [implementation](implementation.md).

Uncertain journals and recovery barriers remain untouched. A source build is not
proof of installed activation; repeat applicable checks after runtime changes.

`eplan_concurrency_status.resource_ownership` reports bounded process-local ownership observations.
Service-manager status reports active owned-tree counts, not a live acceptance certificate. It does
not scan native applications or claim access to every resource record from other processes.

Pure OS-stub tests check containment-before-resume ordering, persisted creation identity, startup
failure, cancellation, timeout, bounded admission, cleanup failure, and continued cleanup after one
resource fails. No real process is launched by these tests. Isolated acceptance after relevant runtime changes must check:

- Direct child and descendant cleanup on normal completion, client EOF, timeout and cancellation.
- Abrupt owner death during creation/assignment/resume and active worker/converter execution.
- Startup/assignment refusal, nested jobs, handle inheritance and capture cleanup on supported Windows/Python versions.
- Preservation of independently launched or attached applications and another owner's shared resources.
- Durable crash records, identity mismatch/PID reuse rejection, cleanup uncertainty and shared-ledger migration.
- Real direct transport, packaged runtime and full regression after the lifecycle changes.

Run those checks only after explicit release of the runtime hold. Never use an engineering project
or user-owned native application as a cleanup fixture.
