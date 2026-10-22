"""Explicit, once-per-checkpoint New York timestamp stamping; never called by runtime/build."""

import argparse
import ast
import json
import re
import tomllib
from pathlib import Path

from eplan_mcp.release_version import canonical_timestamp


def verify(repo):
    module = repo / "src/eplan_mcp/release_version.py"
    stamp = next(
        ast.literal_eval(n.value)
        for n in ast.parse(module.read_text(encoding="utf-8")).body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "DISPLAY_VERSION" for t in n.targets)
    )
    canonical = canonical_timestamp(stamp)
    if (
        tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        != canonical
    ):
        raise ValueError("pyproject identity differs from fixed timestamp")
    for relative in ("plugins/eplan/plugin.json", "plugins/eplan/.codex-plugin/plugin.json"):
        if json.loads((repo / relative).read_bytes())["version"] != canonical:
            raise ValueError("Plugin metadata differs from canonical timestamp")
    if f"Version **{stamp}**." not in (repo / "README.md").read_text(encoding="utf-8"):
        raise ValueError("README display timestamp differs from source")
    return {"display_version": stamp, "package_version": canonical, "timezone": "America/New_York"}


def stamp(repo, value):
    canonical = canonical_timestamp(value)
    module = repo / "src/eplan_mcp/release_version.py"
    module.write_text(
        re.sub(
            r'^DISPLAY_VERSION = "[^"]+"',
            f'DISPLAY_VERSION = "{value}"',
            module.read_text(encoding="utf-8"),
            count=1,
            flags=re.MULTILINE,
        ),
        encoding="utf-8",
        newline="\n",
    )
    project = repo / "pyproject.toml"
    project.write_text(
        re.sub(
            r'^version = "[^"]+"',
            f'version = "{canonical}"',
            project.read_text(encoding="utf-8"),
            count=1,
            flags=re.MULTILINE,
        ),
        encoding="utf-8",
        newline="\n",
    )
    for relative in ("plugins/eplan/plugin.json", "plugins/eplan/.codex-plugin/plugin.json"):
        path = repo / relative
        data = json.loads(path.read_bytes())
        data["version"] = canonical
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    readme = repo / "README.md"
    readme.write_text(
        re.sub(
            r"Version \*\*[^*]+\*\*\.", f"Version **{value}**.", readme.read_text(encoding="utf-8"), count=1
        ),
        encoding="utf-8",
        newline="\n",
    )
    return verify(repo)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--timestamp", help="Explicit, already chosen America/New_York YY.MMDD.HHmmss")
    choice.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    print(json.dumps(verify(repo) if args.verify else stamp(repo, args.timestamp)))


if __name__ == "__main__":
    main()
