import json
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

import pytest
from mcp import Client

from eplan_mcp.config import Config
from eplan_mcp.coordination import Coordinator, ResourceBusy
from eplan_mcp.frontdoor import create_frontdoor


@pytest.mark.parametrize(
    "frontdoors,analysis,actors,mib", [(16, 1, 27, 2688), (20, 1, 31, 3200), (20, 4, 64, 5120)]
)
def test_new_app_envelope_counts_only_admitted_analysis(frontdoors, analysis, actors, mib):
    from eplan_mcp.admission import app_envelope

    result = app_envelope(frontdoors, analysis)
    assert result["processes"] == actors
    assert result["private_commit_bytes"] == mib * 1024 * 1024


def configuration(tmp_path):
    (tmp_path / "sources").mkdir()
    config = tmp_path / "config.json"
    config.write_bytes(
        json.dumps(
            {
                "roots": {"synthetic": str(tmp_path / "sources")},
                "state_dir": str(tmp_path / "state"),
                "max_concurrent_requests": 1,
                "max_queued_requests": 2,
            }
        ).encode()
    )
    return Config.load(config), config


def test_metadata_leases_do_not_acquire_legacy_or_analysis_slots(tmp_path):
    coordinator = Coordinator(tmp_path)
    with ExitStack() as stack:
        for _ in range(4):
            stack.enter_context(coordinator.instance())
        for _ in range(20):
            stack.enter_context(coordinator.frontdoor(identity={"fixture": True}))
        with pytest.raises(ResourceBusy, match="Metadata frontdoor"):
            with coordinator.frontdoor(identity={"fixture": True}):
                pass
        with coordinator.analysis(1):
            with pytest.raises(ResourceBusy, match="Analysis capacity is busy"):
                with coordinator.analysis(1):
                    pass
    with coordinator.frontdoor(identity={"fixture": True}):
        pass
    history = [json.loads(p.read_bytes()) for p in (tmp_path / "frontdoor-leases").glob("*.json")]
    assert len(history) == 21 and all(r["state"] == "closed" for r in history)


def test_partial_initialization_releases_only_its_lease(tmp_path):
    coordinator = Coordinator(tmp_path)
    with pytest.raises(RuntimeError):
        with coordinator.frontdoor(identity={"fixture": True}):
            raise RuntimeError("startup fixture")
    with ExitStack() as stack:
        for _ in range(20):
            stack.enter_context(coordinator.frontdoor(identity={"fixture": True}))


@pytest.mark.anyio
async def test_metadata_and_schemas_available_when_analysis_is_full(tmp_path):
    cfg, path = configuration(tmp_path)
    server = create_frontdoor(cfg, path)
    expected = json.loads(
        Path(__file__).resolve().parents[1].joinpath("src/eplan_mcp/tool_catalog.json").read_bytes()
    )
    async with Client(server, mode="legacy", cache=None) as client:
        tools = await client.list_tools()
        actual = {t.name: t for t in tools.tools}
        assert len(actual) == len(expected["tools"]) == 50
        for row in expected["tools"]:
            assert actual[row["name"]].input_schema == row["inputSchema"]
            assert actual[row["name"]].output_schema == row["outputSchema"]
        with server.eplan_frontdoor.coordinator.analysis(1):
            for name in (
                "eplan_get_workflow",
                "eplan_status",
                "eplan_capabilities",
                "eplan_concurrency_status",
            ):
                result = await client.call_tool(name, {})
                assert not result.is_error, result.content
            busy = await client.call_tool(
                "eplan_read_xml", {"root_id": "synthetic", "relative_path": "fixture.xml"}
            )
            assert busy.is_error and "Analysis capacity is busy" in str(busy.content)
        assert not list((cfg.state / "owned-resources").glob("*.json"))


def test_frontdoor_import_and_catalog_do_not_load_analysis_engines(tmp_path):
    cfg, path = configuration(tmp_path)
    source = Path(__file__).resolve().parents[1] / "src"
    code = "import sys;sys.path.insert(0,sys.argv[1]);from eplan_mcp.config import Config;from eplan_mcp.frontdoor import create_frontdoor;s=create_frontdoor(Config.load(sys.argv[2]),sys.argv[2]);assert not any(n in sys.modules for n in ('numpy','ezdxf','pymupdf'));print(len(s._tool_manager.list_tools()))"
    result = subprocess.run(
        [sys.executable, "-c", code, str(source), str(path)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "50"


def test_metadata_signature_matches_selected_backend_without_inventing_versions(tmp_path):
    from eplan_mcp.service import DrawingService

    cfg, path = configuration(tmp_path)
    metadata = create_frontdoor(cfg, path).eplan_frontdoor.status()
    backend = DrawingService(cfg).status()
    assert metadata["extraction_signature"] == backend["extraction_signature"]
    assert metadata["engines"] == backend["engines"]
