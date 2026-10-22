import copy
import hashlib
from pathlib import Path

import pytest
from mcp import Client
from mcp.types import PaginatedRequestParams, Request
from universal_tools.skill_catalog import SkillGet, SkillList, SkillParams
from universal_tools.skill_client import SkillClient

from eplan_mcp.guidance import BOOTSTRAP, source_bundle
from eplan_mcp.guide_publication import GuidancePublication, digest, publish, read_publication
from eplan_mcp.server import create_server


def payload(result):
    assert not result.is_error, result.content
    return result.structured_content


def test_packaged_bootstrap_is_generated_and_references_are_canonical():
    root = Path(__file__).resolve().parents[1]
    assert (root / "plugins/eplan/skills/eplan-analysis/SKILL.md").read_text() == BOOTSTRAP
    assert len(BOOTSTRAP.splitlines()) < 35
    bundle = source_bundle()
    assert len(bundle["references"]) == 4
    for name, text in bundle["references"].items():
        canonical = (root / "src/eplan_mcp/references" / (name + ".md")).read_text()
        assert text.startswith(canonical)
        if name != "feature-profiles":
            assert text == canonical
        assert len((root / "docs" / (name + ".md")).read_text()) < 250


def test_guidance_state_link_is_rejected_before_publication(drawing_service, monkeypatch):
    drawings, _ = drawing_service
    view = GuidancePublication(drawings.config.state, drawings.coordinator)
    first = view.read()
    original = Path.is_symlink
    linked = drawings.config.state / "guidance"
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == linked or original(path))
    with pytest.raises(ValueError, match="links/junctions"):
        publish(drawings.config.state, drawings.coordinator, expected_revision=first["workflow_revision"])
    assert view.read() == first


@pytest.mark.anyio
async def test_connected_client_guide_catalog_resource_updates_and_failed_publication(drawing_service):
    drawings, _ = drawing_service
    server = create_server(drawings)
    state, coordinator = drawings.config.state, drawings.coordinator
    original = read_publication(state)
    async with Client(server, mode="2026-07-28", extensions=[SkillClient()], cache=None) as client:
        first = payload(await client.call_tool("eplan_get_workflow", {}))
        assert first["workflow_revision"] == original["revision"]
        assert first["sha256"] == digest(first["text"])

        async def listed():
            result = await client.session.send_request(
                Request(method="skills/list", params=PaginatedRequestParams()), SkillList
            )
            assert len(result.skills) == 1
            return result.skills[0]

        async def verify(entry):
            got = await client.session.send_request(
                Request(method="skills/get", params=SkillParams(uri=entry["uri"])), SkillGet
            )
            assert got.skill == entry
            for resource in entry["resources"]:
                raw = (await client.read_resource(resource["uri"])).contents[0].text.encode()
                assert len(raw) == resource["size"]
                assert "sha256:" + hashlib.sha256(raw).hexdigest() == resource["digest"]

        entry = await listed()
        await verify(entry)
        for reference in first["references"]:
            text = payload(await client.call_tool("eplan_get_workflow", reference["read"]["arguments"]))
            resource = (await client.read_resource(reference["uri"])).contents[0].text
            assert text["text"] == resource and digest(resource) == reference["sha256"]

        replacement = copy.deepcopy(original["bundle"])
        replacement["workflow"] += "\nSynthetic published guidance update.\n"
        removed = first["references"][0]
        del replacement["references"][removed["id"]]
        replacement["references"]["synthetic-reference"] = "New offline reference.\n"
        new = publish(state, coordinator, expected_revision=original["revision"], bundle=replacement)
        second = payload(await client.call_tool("eplan_get_workflow", {}))
        assert second["workflow_revision"] == new["workflow_revision"] != first["workflow_revision"]
        assert second["text"] == replacement["workflow"]
        new_entry = await listed()
        assert new_entry != entry
        await verify(new_entry)
        stale = await client.call_tool("eplan_get_workflow", removed["read"]["arguments"])
        assert stale.is_error
        ref = second["references"][0]
        wrong = {**ref["read"]["arguments"], "expected_sha256": "0" * 64}
        assert (await client.call_tool("eplan_get_workflow", wrong)).is_error
        with pytest.raises(Exception):
            await client.read_resource(removed["uri"])

        invalid = copy.deepcopy(replacement)
        invalid["bootstrap"] = "Not a skill manifest"
        with pytest.raises(Exception):
            publish(state, coordinator, expected_revision=second["workflow_revision"], bundle=invalid)
        assert (await listed()) == new_entry
        assert payload(await client.call_tool("eplan_get_workflow", {})) == second
        with pytest.raises(ValueError, match="revision changed"):
            publish(state, coordinator, expected_revision=original["revision"], bundle=replacement)


@pytest.mark.anyio
async def test_tampered_snapshot_cannot_be_published_as_guidance(drawing_service):
    drawings, _ = drawing_service
    publication = GuidancePublication(drawings.config.state, drawings.coordinator)
    revision = publication.read()["workflow_revision"]
    with pytest.raises(ValueError, match="known reference"):
        publication.read(revision, "../../secret", "0" * 64)
    folder = drawings.config.state / "guidance/packages" / revision / "eplan-analysis"
    (folder / "contributed.py").write_text("raise AssertionError('must never execute')")
    with pytest.raises(ValueError, match="inventory"):
        publish(
            drawings.config.state, drawings.coordinator, expected_revision=revision, bundle=source_bundle()
        )
    assert publication.read()["workflow_revision"] == revision


@pytest.mark.anyio
async def test_installed_source_change_requires_explicit_publication(drawing_service, monkeypatch):
    drawings, _ = drawing_service
    publication = GuidancePublication(drawings.config.state, drawings.coordinator)
    first = publication.read()
    changed = source_bundle()
    changed["workflow"] += "\nSynthetic installed-source change.\n"
    monkeypatch.setattr("eplan_mcp.guide_publication.source_bundle", lambda: changed)
    await publication.refresh()
    assert publication.read() == first
    publish(drawings.config.state, drawings.coordinator, expected_revision=first["workflow_revision"])
    await publication.refresh()
    assert publication.read()["text"] == changed["workflow"]


@pytest.mark.anyio
async def test_app_owned_framework_skill_and_backend_guide_share_live_publication(drawing_service, tmp_path):
    from eplan_mcp import framework_host

    drawings, root = drawing_service
    config = root.parent / "config.json"
    host_state = tmp_path / "skill-host"
    published = framework_host.prepare(config, host_state)
    view = GuidancePublication(drawings.config.state, drawings.coordinator)
    async with framework_host.create_host(host_state, Path(published["publication"]), config) as host:
        async with Client(
            host.create_server(
                skills=view.catalog, frontend_identity="synthetic_eplan_guidance_frontend_0001"
            ),
            mode="2026-07-28",
            extensions=[SkillClient()],
            cache=None,
        ) as client:
            desc = payload(
                await client.call_tool("describe_tool", {"tool_id": "drawing-engine/eplan_get_workflow"})
            )

            async def guide():
                return payload(
                    await client.call_tool(
                        desc["invocation"]["channel"],
                        {
                            "tool_id": desc["tool_id"],
                            "catalog_revision": desc["catalog_revision"],
                            "arguments": {},
                        },
                    )
                )

            first = await guide()
            assert (await client.read_resource("skill://eplan-analysis/workflow.md")).contents[
                0
            ].text == first["text"]
            changed = copy.deepcopy(read_publication(drawings.config.state)["bundle"])
            changed["workflow"] += "\nSynthetic app-owned host publication.\n"
            publish(
                drawings.config.state,
                drawings.coordinator,
                expected_revision=first["workflow_revision"],
                bundle=changed,
            )
            second = await guide()
            assert second["workflow_revision"] != first["workflow_revision"]
            assert (await client.read_resource("skill://eplan-analysis/workflow.md")).contents[
                0
            ].text == second["text"]
