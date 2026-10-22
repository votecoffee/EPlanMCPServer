# Feature profiles

The runtime table below is generated from the same feature doctor returned by
`eplan_capabilities.feature_profiles`; no parallel status table is maintained here.

Cancellation is not rollback. The scheduler drains its actual worker thread before releasing
admission or resource ownership, including raw SDK asyncio cancellation. Checkpoints stop further
units; already committed index entries remain. Base-exception cancellation leaves the durable
write receipt uncertain, not silently retryable. Keep the same request ID and inspect effects.
`operation_observations` are bounded to 64 entries per process and are not durable jobs, ownership
leases, restart authorization or cross-chat state. Only the caller's cancellation is bound to that
request; no arbitrary cross-chat cancel tool is provided.

Report resources use `eplan://reports/ep_HASH/OFFSET/LENGTH`. Reassemble the base64 byte chunks and
verify SHA-256 against the snapshot identity. Source freshness metadata is separate from immutable
report bytes. Reads reuse the app's private snapshot store, verified identity and configured state;
they do not claim an independently authenticated per-chat principal. Reads above 16 MiB snapshots
use existing paginated tools instead. Resources never acquire engineering projects or modify files.

Protocol/source/package checks are separate from a host's native progress UI, notification stream,
Skills loader, approval rendering or live engineering acceptance. Reconnect/refetch if hints are
missed. The selected standalone route and cross-process cache/index locks remain unchanged.
