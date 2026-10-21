"""Explicit source allowlist, byte manifest and ZIP verification; never traverses private state."""

import argparse
import hashlib
import json
import tomllib
import zipfile
from pathlib import Path

ROOT_FILES = (
    ".gitattributes",
    "InstallAndRun.cmd",
    "README.md",
    "VERIFICATION.md",
    "AGENTS.md",
    ".gitignore",
    "LICENSE",
    "pyproject.toml",
    "requirements-lock.txt",
    "requirements-dev-lock.txt",
    "NOTICE.md",
)

PRIVATE_DIRECTORIES = {".local", ".venv", "private", "work", "outputs", "__pycache__"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def selected_files(repo):
    files = [repo / name for name in ROOT_FILES]
    for folder in ("src", "scripts", "tests"):
        files.extend((repo / folder).rglob("*.py"))
    files.extend(
        p
        for p in (repo / "examples").rglob("*")
        if p.is_file() and p.suffix in {".json", ".csv", ".xml", ".md"}
    )
    for folder, extension in (("docs", "*.md"), ("schemas", "*.json")):
        files.extend((repo / folder).rglob(extension))
    for path in (repo / "plugins" / "eplan").rglob("*"):
        if path.is_file() and path.suffix.lower() in {".json", ".md", ".png"}:
            files.append(path)
    public = []
    for path in files:
        relative = path.relative_to(repo)
        if any(part.casefold() in PRIVATE_DIRECTORIES for part in relative.parts[:-1]):
            continue
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent != repo.parent):
            raise ValueError("Source packages cannot include symbolic links")
        if not path.resolve(strict=True).is_relative_to(repo.resolve()):
            raise ValueError("Source package member escapes the repository")
        public.append(path)
    return sorted(public, key=lambda path: path.relative_to(repo).as_posix())


def verify(repo):
    manifest = json.loads((repo / "manifest.json").read_text(encoding="utf-8"))
    expected = set(manifest["files"])
    actual = {path.relative_to(repo).as_posix() for path in selected_files(repo)}
    if actual != expected:
        raise ValueError("Manifest file set differs from source allowlist")
    for name, info in manifest["files"].items():
        data = (repo / name).read_bytes()
        if digest(data) != info["sha256"] or len(data) != info["bytes"]:
            raise ValueError(f"Manifest byte mismatch: {name}")
    return {"verified_files": len(expected), "passed": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if args.verify:
        print(json.dumps(verify(repo)))
        return
    if not args.output:
        parser.error("--output is required when packaging")
    files = selected_files(repo)
    manifest = {
        "schema_version": 1,
        "version": tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
        "files": {
            path.relative_to(repo).as_posix(): {
                "sha256": digest(path.read_bytes()),
                "bytes": path.stat().st_size,
            }
            for path in files
        },
    }
    manifest_path = repo / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files + [manifest_path]:
            archive.write(path, "EPlanMCPServer/" + path.relative_to(repo).as_posix())
    with zipfile.ZipFile(target) as archive:
        expected = {"EPlanMCPServer/" + p.relative_to(repo).as_posix() for p in files + [manifest_path]}
        if set(archive.namelist()) != expected or archive.testzip():
            raise ValueError("ZIP contents failed verification")
        for path in files + [manifest_path]:
            name = "EPlanMCPServer/" + path.relative_to(repo).as_posix()
            if archive.read(name) != path.read_bytes():
                raise ValueError(f"ZIP byte mismatch: {name}")
    print(
        json.dumps(
            {
                "zip": str(target),
                "sha256": digest(target.read_bytes()),
                "files": len(files) + 1,
                **verify(repo),
            }
        )
    )


if __name__ == "__main__":
    main()
