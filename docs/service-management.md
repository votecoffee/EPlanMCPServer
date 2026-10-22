# Service management

Framework 0.18.0 provides same-user authenticated loopback reporting to the optional Windows MCP
Service Manager. EPLAN does not install a manager, select a different plugin route or register a
Universal Tools broker. Canonical plugin identity is `eplan@eplan-local`; each owning server/host
process gets a random instance ID. Transient framework workers and proxy clients do not register
as owning services.

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

In-process lock checks cover capacity and exception release. End-to-end startup/termination tests
for this new gate remain pending. The existing clean client-EOF checks do not establish cleanup
after abrupt parent termination, inherited pipe handles, or forced process death. Descendant
termination and a surviving supervisor remain concrete acceptance blockers. No automatic restart,
hidden host startup, process killing, plugin enablement, or journal reconciliation is added.

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
