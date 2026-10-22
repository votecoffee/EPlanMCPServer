"""One explicit, immutable guidance publication for tool readers and Skills-over-MCP."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid

from universal_tools.skill_catalog import SkillCatalog
from universal_tools.skill_manifest import OPENAI_IMPORT_PROFILE

from . import __version__
from .exports import atomic_json, canonical
from .guidance import source_bundle


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def private_path(state, path):
    base = state.resolve()
    if not path.resolve().is_relative_to(base):
        raise ValueError("Guidance path escaped app state")
    for parent in (path, *path.parents):
        if parent == base:
            break
        if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
            raise ValueError("Guidance state links/junctions are not supported")


def validate(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {"workflow", "bootstrap", "references"}:
        raise ValueError("Invalid guidance bundle")
    if any(not isinstance(bundle[k], str) or not bundle[k].strip() for k in ("workflow", "bootstrap")):
        raise ValueError("Guidance instructions must be nonempty text")
    refs = bundle["references"]
    if (
        not isinstance(refs, dict)
        or len(refs) > 16
        or any(
            not isinstance(k, str)
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", k)
            or not isinstance(v, str)
            or not v.strip()
            for k, v in refs.items()
        )
    ):
        raise ValueError("Invalid guidance references")
    if len(canonical(bundle).encode()) > 256 * 1024:
        raise ValueError("Guidance bundle exceeds 256 KiB")
    return digest(canonical(bundle))


def stage(state, bundle):
    revision = validate(bundle)
    folder = state / "guidance" / "packages" / revision / "eplan-analysis"
    private_path(state, folder)
    files = {"SKILL.md": bundle["bootstrap"], "workflow.md": bundle["workflow"]}
    files.update({"references/" + k + ".md": v for k, v in bundle["references"].items()})
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # All paths are app-generated from validated IDs; staging never reads contributed code.
        if path.exists():
            if path.is_symlink() or path.read_bytes() != text.encode():
                raise ValueError("Immutable guidance snapshot changed")
        else:
            temporary = path.with_suffix(path.suffix + "." + uuid.uuid4().hex + ".tmp")
            try:
                temporary.write_bytes(text.encode())
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    if actual != set(files):
        raise ValueError("Guidance snapshot file inventory changed")
    SkillCatalog([folder], profile=OPENAI_IMPORT_PROFILE)  # Validate before changing any pointer.
    return revision, folder


def read_publication(state):
    path = state / "guidance" / "current.json"
    private_path(state, path)
    with path.open("rb") as stream:
        raw = stream.read(300 * 1024 + 1)
    if len(raw) > 300 * 1024:
        raise ValueError("Guidance publication exceeds byte budget")
    body = json.loads(raw)
    if not isinstance(body, dict) or set(body) != {"revision", "bundle"}:
        raise ValueError("Invalid guidance publication")
    if validate(body["bundle"]) != body["revision"]:
        raise ValueError("Guidance publication integrity changed")
    return body


def publish(state, coordinator, *, expected_revision, bundle=None):
    """Explicit local app administration. No engineering receipt or policy is changed."""
    bundle = source_bundle() if bundle is None else bundle
    # Serializes different processes as well as concurrent publication within this process.
    with coordinator.lock("guidance-publication"):
        path = state / "guidance" / "current.json"
        current = read_publication(state)["revision"] if path.exists() else None
        if current != expected_revision:
            raise ValueError("Guidance publication revision changed")
        revision, _ = stage(state, bundle)
        atomic_json(path, {"revision": revision, "bundle": bundle})
        return {"guide_id": "eplan-analysis", "workflow_revision": revision}


class GuidanceCatalog(SkillCatalog):
    async def request_middleware(self, ctx, call_next):
        await self.owner.refresh()
        return await call_next(ctx)


class GuidancePublication:
    def __init__(self, state, coordinator):
        self.state = state
        self.lock = asyncio.Lock()
        if not (state / "guidance" / "current.json").exists():
            with coordinator.lock("guidance-publication"):
                if not (state / "guidance" / "current.json").exists():
                    bundle = source_bundle()
                    revision, _ = stage(state, bundle)
                    atomic_json(state / "guidance" / "current.json", {"revision": revision, "bundle": bundle})
        self.snapshot = read_publication(state)
        _, folder = stage(state, self.snapshot["bundle"])
        self.catalog = GuidanceCatalog([folder], profile=OPENAI_IMPORT_PROFILE)
        self.catalog.owner = self

    async def refresh(self):
        async with self.lock:
            candidate = read_publication(self.state)
            if candidate["revision"] == self.snapshot["revision"]:
                return
            _, folder = stage(self.state, candidate["bundle"])
            await self.catalog.publish([folder], expected_revision=self.catalog.revision)
            self.snapshot = candidate

    def read(self, expected_revision=None, reference_id=None, expected_sha256=None):
        snapshot = self.snapshot
        revision, bundle = snapshot["revision"], snapshot["bundle"]
        if expected_revision is not None and expected_revision != revision:
            raise ValueError("Stale workflow revision; rediscover current guidance")
        base = {
            "schema_version": 2,
            "guide_id": "eplan-analysis",
            "app_version": __version__,
            "workflow_revision": revision,
            "skill_catalog_revision": self.catalog.revision,
        }
        if reference_id is not None:
            if expected_revision is None or reference_id not in bundle["references"]:
                raise ValueError("Select a current workflow revision and known reference ID")
            text = bundle["references"][reference_id]
            if expected_sha256 != digest(text):
                raise ValueError("Stale or missing reference SHA-256")
            return {**base, "reference_id": reference_id, "sha256": digest(text), "text": text}
        if expected_sha256 is not None:
            raise ValueError("expected_sha256 requires reference_id")
        refs = []
        for name, text in bundle["references"].items():
            refs.append(
                {
                    "id": name,
                    "sha256": digest(text),
                    "uri": f"skill://eplan-analysis/references/{name}.md",
                    "read": {
                        "tool": "eplan_get_workflow",
                        "arguments": {
                            "expected_revision": revision,
                            "reference_id": name,
                            "expected_sha256": digest(text),
                        },
                    },
                }
            )
        return {**base, "text": bundle["workflow"], "sha256": digest(bundle["workflow"]), "references": refs}
