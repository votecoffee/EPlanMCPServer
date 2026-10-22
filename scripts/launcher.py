"""Windows CMD bootstrap: keep the environment and private state inside this checkout."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def install(command):
    # stdout belongs to the MCP protocol in --stdio mode, including during setup.
    subprocess.run(command, cwd=REPO, stdout=sys.stderr, stderr=sys.stderr, check=True)


def main():
    raise ValueError("Bootstrap and shell-wrapper lifecycle profile is unaccepted; automatic installation/startup is disabled")


def _main_unaccepted():
    parser = argparse.ArgumentParser(description="Install dependencies locally and run EPLAN MCP Server")
    parser.add_argument(
        "--install-only", action="store_true", help="Install and validate configuration without starting"
    )
    parser.add_argument("--stdio", action="store_true", help="Use MCP stdio instead of loopback HTTP")
    parser.add_argument(
        "--framework-wheel", help="Verified local SDK 2.3 shared framework wheel; cached privately"
    )
    parser.add_argument(
        "--install-plugin", action="store_true", help="Explicitly install the standalone Codex plugin"
    )
    parser.add_argument(
        "--codex-integration",
        choices=["auto", "standalone", "none"],
        default=None,
        help="Default: refresh standalone during setup; preserve saved skip/disabled choices; none for --stdio",
    )
    parser.add_argument("--port", type=int, default=8816, help="Loopback HTTP port (default: 8816)")
    parser.add_argument(
        "--root", action="append", help="First setup only: alias=absolute drawing directory (repeatable)"
    )
    args = parser.parse_args()
    if args.install_plugin and args.codex_integration not in {None, "standalone"}:
        parser.error("--install-plugin selects standalone; do not combine with another integration mode")
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be 1..65535")
    from framework_dependency import stage

    wheel_directory = stage(REPO, args.framework_wheel)
    environment = REPO / ".venv"
    python = environment / "Scripts" / "python.exe"
    uv = shutil.which("uv")
    if not python.exists():
        print("Creating the application environment in .venv ...", file=sys.stderr)
        import venv

        venv.EnvBuilder(with_pip=not bool(uv)).create(environment)
    print("Installing locked dependencies and the application ...", file=sys.stderr)
    if uv:
        install(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--reinstall-package",
                "universal-codex-tools",
                "--require-hashes",
                "--only-binary",
                ":all:",
                "--find-links",
                str(wheel_directory),
                "-r",
                str(REPO / "requirements-lock.txt"),
            ]
        )
        install([uv, "pip", "install", "--python", str(python), "--no-deps", "-e", str(REPO)])
    else:
        probe = subprocess.run(
            [str(python), "-m", "pip", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if probe.returncode:
            install([str(python), "-m", "ensurepip", "--upgrade"])
        install(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--require-hashes",
                "--only-binary",
                ":all:",
                "--find-links",
                str(wheel_directory),
                "-r",
                str(REPO / "requirements-lock.txt"),
            ]
        )
        install([str(python), "-m", "pip", "install", "--no-deps", "-e", str(REPO)])
    config = Path(os.environ.get("EPLAN_MCP_CONFIG") or REPO / ".local" / "config.json").resolve()
    if not config.exists():
        if config != (REPO / ".local" / "config.json").resolve():
            parser.error("EPLAN_MCP_CONFIG does not name an existing configuration")
        roots = args.root
        if not roots:
            if args.stdio or not sys.stdin.isatty():
                parser.error(
                    'No configuration. Run InstallAndRun.cmd --root "drawings=C:\\Engineering\\Drawings" --install-only first'
                )
            directory = input("Drawing folder (full path): ").strip().strip('"')
            if not directory:
                parser.error("A drawing folder is required for first setup")
            roots = ["drawings=" + directory]
        command = [str(python), str(REPO / "scripts" / "configure.py")]
        for root in roots:
            command.extend(["--root", root])
        install(command)
    elif args.root:
        parser.error("Existing configuration preserved. Edit .local/config.json to change roots")
    install([str(python), "-m", "eplan_mcp", "--config", str(config), "status"])
    integration = args.codex_integration or ("none" if args.stdio else "auto")
    if args.install_plugin:
        integration = "standalone"
    # Protocol startup must not alter installation routing implicitly.
    if integration != "none" or args.codex_integration == "none":
        install(
            [
                str(python),
                str(REPO / "scripts" / "install_plugin.py"),
                "--mode",
                integration,
                "--config",
                str(config),
            ]
        )
    if args.install_only:
        print("Installation and configuration verified.", file=sys.stderr)
        return 0
    transport = "stdio" if args.stdio else "streamable-http"
    if not args.stdio:
        print(f"Starting EPLAN MCP Server at http://127.0.0.1:{args.port}/mcp", file=sys.stderr)
        print("Keep this window open. Press Ctrl+C to stop.", file=sys.stderr)
    return subprocess.call(
        [
            str(python),
            "-m",
            "eplan_mcp",
            "--config",
            str(config),
            "serve",
            "--transport",
            transport,
            "--port",
            str(args.port),
        ],
        cwd=REPO,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"Installation failed (exit {error.returncode}). See the output above.", file=sys.stderr)
        raise SystemExit(error.returncode or 1)
    except KeyboardInterrupt:
        print("Server stopped.", file=sys.stderr)
        raise SystemExit(130)
    except (ValueError, OSError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        raise SystemExit(1)
