"""Explicit source installer; never starts a server or edits global Codex settings."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

try:
    from .framework_dependency import stage
except ImportError:
    from framework_dependency import stage

REPO = Path(__file__).resolve().parents[1]


def install(command):
    subprocess.run(command, cwd=REPO, stdout=sys.stderr, stderr=sys.stderr, check=True, timeout=600)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install-only",
        action="store_true",
        help="Install only (the default); no server or plugin activation",
    )
    parser.add_argument(
        "--framework-wheel", help="Exact reviewed local framework wheel; no public replacement"
    )
    parser.add_argument("--root", action="append", help="First setup only: alias=absolute source directory")
    parser.add_argument(
        "--prepare-plugin",
        action="store_true",
        help="Stage standalone plugin files locally; do not register or enable them",
    )
    parser.add_argument("--offline", action="store_true", help="Use cached dependency/build wheels only")
    parser.add_argument(
        "--stdio",
        action="store_true",
        help="Retained legacy flag; use the explicit server command after setup",
    )
    args = parser.parse_args(argv)
    if args.stdio:
        parser.error(
            "This installer does not start servers; run .venv\\Scripts\\python.exe -m eplan_mcp --config .local/config.json serve explicitly"
        )
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required")
    config = REPO / ".local/config.json"
    if config.exists() and args.root:
        parser.error("Existing configuration preserved; --root applies only to first setup")
    wheel_directory = stage(REPO, args.framework_wheel)
    environment = REPO / ".venv"
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    uv = shutil.which("uv")
    if not python.is_file():
        venv.EnvBuilder(with_pip=not bool(uv)).create(environment)
    if uv:
        prefix = [uv, "pip", "install", "--python", str(python)]
        offline = ["--offline"] if args.offline else []
    else:
        prefix = [str(python), "-m", "pip", "install"]
        offline = ["--no-index"] if args.offline else []
    install(
        prefix
        + offline
        + [
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--find-links",
            str(wheel_directory),
            "-r",
            str(REPO / "requirements-lock.txt"),
        ]
    )
    install(prefix + offline + ["--no-deps", str(REPO)])
    if not config.exists():
        roots = args.root
        if not roots:
            workspace = REPO / ".local/workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            roots = ["local=" + str(workspace)]
        command = [str(python), str(REPO / "scripts/configure.py")]
        for value in roots:
            command.extend(["--root", value])
        install(command)
    if args.prepare_plugin:
        install(
            [str(python), str(REPO / "scripts/install_plugin.py"), "--prepare-only", "--config", str(config)]
        )
    print(
        json.dumps(
            {
                "installed": True,
                "config": str(config),
                "server_started": False,
                "plugin_activated": False,
                "global_config_written": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"Installation failed (exit {error.returncode}).", file=sys.stderr)
        raise SystemExit(error.returncode or 1)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        raise SystemExit(130)
