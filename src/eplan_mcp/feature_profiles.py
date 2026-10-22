"""Discoverable assessment of the app-selected profiles, not dependency feature claims."""


def profiles():
    def item(status, reason):
        return {"status": status, "reason": reason}

    return {
        "assessment_scope": "Offline/synthetic app and protocol checks; native host acceptance is separate",
        "selected_profile": "direct-standalone-offline",
        "vendor_native_readers": item(
            "blocked",
            "ODA discovery/configuration/conversion and direct/archive/worker Access reads refused; no environment opt-in",
        ),
        "http_transport": item(
            "blocked", "Only direct stdio serving is enabled; HTTP startup refused before config load"
        ),
        "framework_020_runtime": item(
            "implemented-but-unassessed",
            "Reviewed 0.20 wheel/pins and synthetic ledger adapter checks; installed/MCP/native lifecycle acceptance pending",
        ),
        "endpoint_instance_admission": item(
            "implemented-but-unassessed",
            "Four non-waiting cross-process slots per app state; source-only lock checks, server startup acceptance pending",
        ),
        "parent_exit_cleanup": item(
            "implemented-but-unassessed",
            "Harmless Python owner-death/descendant fixtures passed; actual MCP EOF/upstream-client loss still pending",
        ),
        "owned_process_lifecycle": item(
            "implemented-but-unassessed",
            "Harmless Python startup/timeout/cancel/normal/descendant fixtures passed; actual MCP worker path still pending",
        ),
        "shared_resource_ledger": item(
            "implemented-but-unassessed",
            "Framework 0.20 reservations/binding/reconciliation tested with synthetic identities; real Windows and manager recovery acceptance pending",
        ),
        "framework_host_ownership": item(
            "blocked",
            "Serve/proxy entry points refuse startup until shared leases and framework backend-tree containment are accepted",
        ),
        "installer_lifecycle": item(
            "blocked",
            "Bootstrap and plugin-install external wrappers refuse execution pending a contained installer ownership profile",
        ),
        "skills_and_guides": item(
            "enabled-and-tested", "Canonical tool/reference/catalog reads; explicit atomic publication"
        ),
        "direct_discovery_cache": item(
            "enabled-and-tested",
            "Modern tools/list only; private 1000 ms TTL; invocation still runs policy/revision checks",
        ),
        "guidance_notifications": item(
            "implemented-but-unassessed",
            "Framework live resource notifications wired; reconnect/refetch tested, native host delivery not accepted",
        ),
        "framework_catalog_watch": item(
            "blocked",
            "Selected backend is transient legacy; retained auto/modern ownership migration has not been authorized",
        ),
        "index_and_import_progress": item(
            "enabled-and-tested", "Monotonic file/report stages and structured process-local observations"
        ),
        "cooperative_cancellation": item(
            "enabled-and-tested",
            "Queued/dispatch and between-file/report-row checkpoints; in-flight workers are not preempted and durable uncertain receipts remain",
        ),
        "local_data_cancellation": item(
            "blocked",
            "Single parser subprocesses lack intra-worker cooperative checkpoints; existing worker budgets/cleanup remain",
        ),
        "tasks": item(
            "blocked",
            "No durable app-owned batch job/worker lifecycle or trusted job-owner binding; synchronous analysis does not survive process loss",
        ),
        "approval_continuations": item(
            "outside-workflow",
            "No native engineering writes; ordinary private offline analysis does not need new approval prompts",
        ),
        "direct_report_resources": item(
            "enabled-and-tested",
            "Private snapshot IDs, verified content hash/freshness, 16000-byte reads; query tools remain available",
        ),
        "framework_report_relay": item(
            "blocked",
            "No app-authorized report resource relay configured; ordinary backend report tools remain available",
        ),
        "report_update_notifications": item(
            "blocked",
            "Report identities are immutable; no authorized source-freshness watcher or mutable per-owner artifact channel exists",
        ),
        "native_codex_skills": item(
            "implemented-but-unassessed",
            "Packaged bootstrap retained; protocol tests do not activate the native loader",
        ),
        "redis_oauth_apps": item(
            "outside-workflow", "Optional profiles are not required or enabled by this app"
        ),
    }
