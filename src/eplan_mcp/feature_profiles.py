"""Discoverable assessment of the app-selected profiles, not dependency feature claims."""


def profiles(profile="direct-standalone-offline", converter=False):
    def item(status, reason):
        return {"status": status, "reason": reason}

    return {
        "assessment_scope": "Implementation availability; selected direct-profile lifetime coverage is separate from current artifact and host acceptance",
        "selected_profile": profile,
        "native_thread_pool_policy": item(
            "implemented",
            "Fixed standalone pre-import numerical limits; preloaded hosts refused; selected direct runtime measurements are separate from configured limits",
        ),
        "vendor_native_readers": item(
            "configured" if converter else "not-configured",
            "Explicit profile and pinned ODA copy-only conversion; selected DWG read/preview and descendant cleanup covered. Revalidate changed vendor/runtime bytes. Access/ACE stays disabled.",
        ),
        "http_transport": item(
            "blocked", "Only direct stdio serving is enabled; HTTP startup refused before config load"
        ),
        "framework_020_runtime": item(
            "implemented",
            "Reviewed 0.20 wheel/pins; selected direct MCP/ODA lifetime coverage; optional shared host is not selected",
        ),
        "endpoint_instance_admission": item(
            "implemented",
            "Twelve lightweight metadata leases per state; at most four on-demand analysis operations (configuration may be narrower). Parser/ODA limits are unchanged. Legacy endpoint leases are never stolen.",
        ),
        "parent_exit_cleanup": item(
            "implemented",
            "Selected direct EOF, client loss with held writer, supervisor death and ODA descendants covered; no shared GUI adoption",
        ),
        "owned_process_lifecycle": item(
            "implemented",
            "Handle-bound normal/failure/cancellation teardown and selected actual MCP/ODA descendant coverage; no PID/name cleanup",
        ),
        "shared_resource_ledger": item(
            "implemented",
            "Reservations, creation-bound binding, reconciliation and revision-bound orphan/idempotence covered; uncertain barriers preserved",
        ),
        "framework_host_ownership": item(
            "blocked",
            "Serve/proxy entry points refuse startup until shared leases and framework backend-tree containment are accepted",
        ),
        "installer_lifecycle": item(
            "setup-only",
            "Install-only setup and disposable CMD forwarding/help/failure checks; no server/native/plugin/global-config activation. Automatic plugin registration remains unavailable.",
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
            "Optional framework host is not selected; standalone SDK discovery uses its immutable per-generation catalog",
        ),
        "index_and_import_progress": item(
            "final-observations",
            "Backend returns real final file/report stage observations; frontend counters show admission, not live backend stages. Live stage streaming is not advertised.",
        ),
        "cooperative_cancellation": item(
            "owned-tree-cancellation",
            "Frontend disconnect/cancellation stops its owned ephemeral analysis tree. Committed private units remain; interrupted write receipts can stay unknown. Never infer rollback or replay.",
        ),
        "local_data_cancellation": item(
            "owned-tree-cancellation",
            "Single parsers have no intra-worker checkpoints; their private owned trees stop on cancellation under existing worker budgets. No native editor or shared software is acquired.",
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
