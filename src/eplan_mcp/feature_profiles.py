"""Discoverable assessment of the app-selected profiles, not dependency feature claims."""


def profiles():
    def item(status, reason):
        return {"status": status, "reason": reason}

    return {
        "assessment_scope": "Offline/synthetic app and protocol checks; native host acceptance is separate",
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
