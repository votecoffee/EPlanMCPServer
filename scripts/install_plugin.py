"""Prepare an independent app-owned Codex plugin with private local runtime bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FILES = (
    "plugin.json",
    "mcp.json",
    ".mcp.json",
    ".codex-plugin/plugin.json",
    "skills/eplan-analysis/SKILL.md",
)


def prepare(
    repo: Path,
    config: Path | None = None,
    *,
    frontend="legacy",
    host_state: Path | None = None,
    stable_root: Path | None = None,
):
    repo = repo.resolve()
    template = repo / "plugins" / "eplan"
    config = (config or repo / ".local" / "config.json").resolve(strict=True)
    from eplan_mcp.config import Config
    from eplan_mcp.release_version import DISPLAY_VERSION, PACKAGE_VERSION

    Config.load(config)
    if stable_root is None:
        raise ValueError("Prepare a reviewed stable installation before publishing a plugin binding")
    try:
        from .stable_launcher import verify
    except ImportError:
        from stable_launcher import verify
    selection, _, snapshot = verify(stable_root)
    if json.loads((snapshot / "config.json").read_bytes()) != json.loads(config.read_bytes()):
        raise ValueError("Plugin configuration differs from selected immutable runtime")
    server = {
        "type": "stdio",
        "command": selection["interpreter"],
        "args": ["-I", "-B", str(stable_root / "Start-Mcp.py")],
        "cwd": str(stable_root),
    }
    if frontend == "framework":
        raise ValueError("Optional framework host is not selected; stable direct binding only")
    elif frontend != "legacy" or host_state is not None:
        raise ValueError("Select legacy or framework explicitly; host state applies only to framework")
    portable = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        "mcpServers": {"eplan": server},
    }
    legacy = {"mcpServers": {"eplan": server}}
    contents = {name: (template / name).read_bytes() for name in FILES}
    contents["mcp.json"] = (json.dumps(portable, indent=2) + "\n").encode()
    contents[".mcp.json"] = (json.dumps(legacy, indent=2) + "\n").encode()
    digest = hashlib.sha256(
        b"".join(name.encode() + b"\0" + contents[name] for name in sorted(contents))
    ).hexdigest()[:16]
    root = repo / ".local" / "codex-marketplace"
    package = root / "packages" / ("eplan-" + PACKAGE_VERSION + "-" + digest)
    for name, data in contents.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Immutable plugin package identity conflict")
        if not path.exists():
            path.write_bytes(data)
    marketplace = {
        "name": "eplan-local",
        "interface": {"displayName": "EPLAN MCP Server Local"},
        "plugins": [
            {
                "name": "eplan",
                "source": {"source": "local", "path": "./" + package.relative_to(root).as_posix()},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        ],
    }
    target = root / ".agents" / "plugins" / "marketplace.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    from eplan_mcp.electrical import atomic_json

    atomic_json(target, marketplace)
    return {
        "marketplace": str(root),
        "package": str(package),
        "plugin": "eplan@eplan-local",
        "transport": "stdio",
        "standalone": True,
        "frontend": frontend,
        "display_version": DISPLAY_VERSION,
        "package_version": PACKAGE_VERSION,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare-only", action="store_true", help="Prepare local bindings without registering in Codex"
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "standalone", "none"],
        default="standalone",
        help="Auto refreshes standalone while preserving skipped/disabled installation choices",
    )
    parser.add_argument("--config", type=Path, help="Use this app configuration in the generated binding")
    parser.add_argument("--frontend", choices=["legacy", "framework"], default="legacy")
    parser.add_argument("--host-state", type=Path, help="Dedicated app-owned framework host state")
    parser.add_argument("--stable-root", type=Path, help="Reviewed durable application installation")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    config = (args.config or repo / ".local/config.json").resolve(strict=True)

    if args.prepare_only:
        print(
            json.dumps(
                prepare(
                    repo,
                    config,
                    frontend=args.frontend,
                    host_state=args.host_state,
                    stable_root=args.stable_root,
                )
            )
        )
        return
    raise ValueError("Plugin installation is blocked pending owned CLI/wrapper lifecycle acceptance")


if __name__ == "__main__":
    main()
