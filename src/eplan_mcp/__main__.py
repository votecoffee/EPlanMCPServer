from __future__ import annotations

import argparse
import json
import os
import sys


def main():
    from .owned_processes import owner_scope

    with owner_scope(exclusive=True):
        return _main()


def _main():
    if len(sys.argv) > 1 and sys.argv[1] in {"_extract", "_render", "_tables", "_local"}:
        from .owned_processes import bind_evidence

        if state := os.environ.get("EPLAN_RESOURCE_OWNER_STATE"):
            bind_evidence(state)
        if sys.argv[1] == "_extract":
            from .extract import run_worker
        elif sys.argv[1] == "_render":
            from .render import run_worker
        elif sys.argv[1] == "_tables":
            from .render import run_tables as run_worker
        else:
            from .local_data import run_worker
        run_worker(*sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description="EPLAN MCP Server - local DWG/DXF/PDF extraction")
    from . import __version__

    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", default=os.environ.get("EPLAN_MCP_CONFIG", ".local/config.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--port", type=int, default=8816)
    serve.add_argument(
        "--workflow", action="store_true", help="Expose the backend's versioned workflow read tool"
    )
    prepare = sub.add_parser(
        "framework-prepare", help="Publish a private, immutable backend for the app-owned framework host"
    )
    prepare.add_argument("--host-state", required=True)
    prepare.add_argument("--port", type=int, default=8818)
    prepare.add_argument("--include-highlighting", action="store_true")
    host = sub.add_parser("framework-serve", help="Run the authenticated app-owned host; no universal daemon")
    host.add_argument("--host-state", required=True)
    host.add_argument("--publication")
    proxy = sub.add_parser(
        "framework-proxy", help="Connect the standalone app frontend to its already-running host"
    )
    proxy.add_argument("--host-state", required=True)
    sub.add_parser("status")
    guidance_publish = sub.add_parser(
        "guidance-publish", help="Explicitly publish installed app guidance to connected readers"
    )
    guidance_publish.add_argument("--expected-revision", required=True)
    inventory = sub.add_parser("inventory")
    inventory.add_argument("root_id")
    inventory.add_argument("--all", action="store_true")
    inventory.add_argument("--offset", type=int, default=0)
    inventory.add_argument("--limit", type=int, default=100)
    for name in ("inspect", "text", "render"):
        command = sub.add_parser(name)
        command.add_argument("root_id")
        command.add_argument("relative_path")
    index = sub.add_parser("index")
    index.add_argument("root_id")
    index.add_argument("--offset", type=int, default=0)
    index.add_argument("--limit", type=int, default=2)
    search = sub.add_parser("search")
    search.add_argument("root_id")
    search.add_argument("query")
    build = sub.add_parser("electrical-build")
    build.add_argument("root_id")
    build.add_argument("--wdp")
    build.add_argument("--options", help="JSON file with build options, including reports and drawing_paths")
    for name in ("electrical-show", "electrical-export"):
        command = sub.add_parser(name)
        command.add_argument("project_id")
        if name == "electrical-show":
            command.add_argument("--collection")
            command.add_argument("--offset", type=int, default=0)
            command.add_argument("--limit", type=int, default=50)
            command.add_argument("--query")
    trace = sub.add_parser("electrical-trace")
    trace.add_argument("project_id")
    trace.add_argument("device_id")
    trace.add_argument("--terminal")
    trace.add_argument("--domain", choices=["electrical", "network"], default="electrical")
    compare = sub.add_parser("electrical-compare")
    compare.add_argument("before_project_id")
    compare.add_argument("after_project_id")
    export_import = sub.add_parser("import-reports")
    export_import.add_argument("root_id")
    export_import.add_argument("declarations", help="JSON file containing report declarations")
    for operation in ("snapshot", "snapshot-export", "snapshot-check"):
        cmd = sub.add_parser(operation)
        cmd.add_argument("snapshot_id")
    cmd = sub.add_parser("snapshot-query")
    cmd.add_argument("snapshot_id")
    cmd.add_argument("kind")
    cmd.add_argument("--query")
    cmd.add_argument("--offset", type=int, default=0)
    cmd.add_argument("--limit", type=int, default=50)
    local = sub.add_parser(
        "local-read", help="Independent XML, Access, project-link and binary evidence reader"
    )
    local.add_argument("root_id")
    local.add_argument("relative_path")
    local.add_argument(
        "operation", choices=["xml", "access", "project", "bytes", "text", "streams", "slots", "archive"]
    )
    local.add_argument(
        "--options", help="JSON file with reader options such as record_tag, table, offset and limit"
    )
    for name in ("device-profile", "supply-trace"):
        command = sub.add_parser(name)
        command.add_argument("snapshot_id")
        command.add_argument("tag")
        command.add_argument("--installation")
        command.add_argument("--location")
        if name == "supply-trace":
            command.add_argument("--medium", choices=["electrical", "pneumatic"], default="electrical")
            command.add_argument("--terminal")
    evidence = sub.add_parser("device-evidence")
    evidence.add_argument("root_id")
    evidence.add_argument("drawing_paths", nargs="+")
    evidence.add_argument("--device-query")
    evidence.add_argument("--category", choices=["device", "ip", "power", "air", "io"])
    evidence.add_argument("--radius", type=float, default=80)
    evidence.add_argument("--offset", type=int, default=0)
    evidence.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    if args.command == "serve" and args.transport != "stdio":
        raise ValueError("Only direct stdio serving is enabled in the standalone offline profile")
    if args.command.startswith("framework-"):
        from pathlib import Path

        from . import framework_host

        state = Path(args.host_state)
        if args.command == "framework-prepare":
            result = framework_host.prepare(
                Path(args.config), state, port=args.port, highlighting=args.include_highlighting
            )
            print(json.dumps(result))
        elif args.command == "framework-serve":
            framework_host.serve(
                state,
                Path(args.publication) if args.publication else state / "eplan-application.json",
                Path(args.config),
            )
        else:
            framework_host.proxy(state)
        return
    from .config import Config
    from .service import DrawingService

    service = DrawingService(Config.load(args.config))
    from .owned_processes import bind_evidence

    bind_evidence(service.config.state)
    if args.command == "guidance-publish":
        from .guide_publication import publish

        print(
            json.dumps(
                publish(service.config.state, service.coordinator, expected_revision=args.expected_revision)
            )
        )
        return
    if args.command in {"device-profile", "supply-trace", "device-evidence"}:
        from .device_information import DeviceInformation, collect_evidence

        if args.command == "device-evidence":
            result = collect_evidence(
                service,
                args.root_id,
                args.drawing_paths,
                args.device_query,
                args.category,
                args.radius,
                args.offset,
                args.limit,
            )
        elif args.command == "device-profile":
            result = DeviceInformation(service).profile(
                args.snapshot_id, args.tag, args.installation, args.location
            )
        else:
            result = DeviceInformation(service).supply(
                args.snapshot_id, args.tag, args.medium, args.terminal, args.installation, args.location
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "local-read":
        from pathlib import Path

        from .local_data import LocalDataService

        options = json.loads(Path(args.options).read_text(encoding="utf-8-sig")) if args.options else {}
        local = LocalDataService(service)
        result = (
            local.project(args.root_id, args.relative_path, **options)
            if args.operation == "project"
            else local.read(args.root_id, args.relative_path, args.operation, **options)
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command == "serve":
        from .management import Reporting
        from .server import SDK2, create_server

        with service.coordinator.instance():
            server = create_server(service, args.port, workflow=args.workflow)
            with Reporting(
                service.config.state,
                server.eplan_scheduler.status,
                role="Per-chat stdio connection" if args.transport == "stdio" else "Standalone loopback service",
            ):
                if args.transport == "stdio" or not SDK2:
                    server.run(transport=args.transport)
                else:
                    server.run(transport="streamable-http", host="127.0.0.1", port=args.port)
        return
    if args.command in {"import-reports", "snapshot", "snapshot-export", "snapshot-check", "snapshot-query"}:
        from pathlib import Path

        from .exports import ExportService

        exports = ExportService(service)
        if args.command == "import-reports":
            result = exports.import_reports(
                args.root_id, json.loads(Path(args.declarations).read_text(encoding="utf-8-sig"))
            )
        elif args.command == "snapshot-query":
            result = exports.query(args.snapshot_id, args.kind, args.query, args.offset, args.limit)
        else:
            operation = {
                "snapshot": exports.get,
                "snapshot-export": exports.export,
                "snapshot-check": exports.checks,
            }[args.command]
            result = operation(args.snapshot_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.command.startswith("electrical-"):
        from pathlib import Path

        from .electrical import ElectricalService

        electrical = ElectricalService(service)
        if args.command == "electrical-build":
            options = json.loads(Path(args.options).read_text(encoding="utf-8-sig")) if args.options else {}
            if args.wdp:
                options["electrical_project_path"] = args.wdp
            result = electrical.build(args.root_id, **options)
        elif args.command == "electrical-show":
            result = (
                electrical.query(args.project_id, args.collection, args.offset, args.limit, args.query)
                if args.collection
                else electrical.get(args.project_id)
            )
        elif args.command == "electrical-trace":
            result = electrical.trace(args.project_id, args.device_id, args.terminal, args.domain)
        elif args.command == "electrical-compare":
            result = electrical.compare(args.before_project_id, args.after_project_id)
        else:
            result = electrical.export(args.project_id)
    elif args.command == "status":
        result = service.status()
    elif args.command == "inventory":
        result = service.inventory(args.root_id, not args.all, args.offset, args.limit)
    elif args.command == "inspect":
        result = service.inspect(args.root_id, args.relative_path)
    elif args.command == "text":
        result = service.records(args.root_id, args.relative_path, "text")
    elif args.command == "render":
        result = service.render(args.root_id, args.relative_path)
    elif args.command == "index":
        result = service.index(args.root_id, args.offset, args.limit)
    else:
        result = service.search(args.root_id, args.query)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
