# Service management

The selected direct profiles have Windows transport/process-lifetime coverage, including
active/queued EOF, cancellation, client/supervisor loss, ODA descendant cleanup and
revision-bound orphan receipt idempotence. Repeat applicable acceptance when runtime
or vendor bytes change. Optional host/shared-GUI profiles remain separate.

[CodexMCPBroker](https://github.com/votecoffee/CodexMCPBroker) provides the shared Python
framework and the separate optional Windows MCP Service Manager application. Framework
0.20.0 supplies same-user authenticated loopback reporting. EPLAN does not install the
manager, select a different plugin route or register a
Universal Tools broker. Canonical plugin identity is `eplan@eplan-local`; each owning server/host
process gets a random instance ID. Transient framework workers and proxy clients do not register
as owning services.

The architecture is the shared app framework plus the independent Windows manager. EPLAN keeps
its own Codex plugin and native skill. No universal Codex plugin or connection is required,
installed, composed or used to choose EPLAN installation. The Python distribution/import names
`universal-codex-tools` and `universal_tools` identify the shared library; they do not imply a
universal plugin deployment. Framework 0.20.0 pins and reviewed wheel bytes are updated in source;
updating that pin alone does not migrate a running process or independently installed manager.

The direct server reports admitted/queued analysis and control work from its scheduler. The
app-owned framework host counts backend invocations, including failures. Counts describe that
instance only. Cross-process cache/index locks retain their existing behavior. Status callbacks
use guarded cached version metadata and activity counters, without reading engineering files,
attaching native projects, contacting controllers or scanning networks.

Installed/running app, plugin, framework and SDK versions remain distinct. Installer metadata
records the selected plugin version only after successful plugin installation. Missing plugin
metadata stays unknown. Installer/package metadata refreshes every five seconds; no remote update
feed is queried. Available versions remain null and update_pending is explicitly false without
an available update source. The dashboard separately detects installed/running mismatch.

Restart is disabled with a specific reason: there is no surviving EPLAN app supervisor and no
cross-chat fence covering queued operations, unresolved receipts and all other sessions. The
app callback always returns blocked. Neither the manager nor EPLAN kills/relaunches a PID,
clears barriers, retries effects, reconciles unknown outcomes automatically or interrupts chats.
The framework's durable at-most-once journal remains authoritative for management requests.

Default registration uses the Windows Local AppData known-folder registry supplied by the
framework. Credentials and registration files stay outside public Git and logs. Tests can set
`EPLAN_MANAGEMENT_REGISTRY` to a dedicated private directory. Stopped registrations remain visible;
an unreachable old process cannot become restartable. Normal shutdown closes reporting threads
and publishes stopped state. Acceptance of a hypothetical future restart would still not prove
replacement health.

New server processes report automatically. Updating package files does not convert an already
running chat process into a reporting process; its normal reconnect is separate acceptance.
No native EPLAN project access or safe production-process restart is claimed by this integration.

## Instance lifecycle and test isolation

Source-level admission now holds one of four non-waiting OS file-lock slots for the lifetime of
each direct analysis endpoint or app-owned framework host using the same app state. Framework
analysis backends also consume direct endpoint slots. Admission occurs before transport startup
and management registration; capacity rejects without retrying or starting another service.
Normal/exceptional exit releases the slot, and process death releases the OS lock. Lock files are
not PID inventories and must not be deleted to bypass admission. Separate state directories have
separate limits; this is not a system-wide memory bound or a shared supervisor.

Selected-profile checks include capacity, exception release, abrupt client/owner loss,
inherited-pipe preservation and ODA descendant cleanup. Lock-file presence alone is not
proof of a held lock; never delete locks to bypass admission. A private test watchdog is
not a system-wide resource quota or permission to interrupt another session. Automatic
restart, shared-GUI adoption and semantic EPLAN project access remain outside this profile.

The default standalone stdio route owns one server per live connection; multiple responding rows
can be legitimate different chats. Status labels distinguish per-chat stdio connections, standalone
loopback services and the app-owned framework host. Historical stopped/offline rows are not proof
of currently running processes or permission to kill them. Inspect the owning connection/process
chain before any shutdown; never clear journals or bulk-kill by executable name.

Every test/acceptance stdio process must pass `EPLAN_MANAGEMENT_REGISTRY` explicitly in its transport
environment. The SDK filters inherited environment variables, so a parent-only environment override
is insufficient. Public stdio tests and the smoke script set it explicitly and verify clean EOF
shutdown/stopped registration in their private registry. In-memory tests do not register processes.
Disposable framework workers do not register as supervisors. A zero operation counter does not
prove safe shutdown; live user sessions, pending effects and uncertain receipts remain untouched.
