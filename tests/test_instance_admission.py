"""In-process lock checks only; no server, plugin, native app or subprocess startup."""

from contextlib import ExitStack

import pytest

from eplan_mcp.coordination import Coordinator, ResourceBusy


def test_instance_limit_shared_by_coordinators_and_released(tmp_path):
    first, second = Coordinator(tmp_path), Coordinator(tmp_path)
    with ExitStack() as active:
        for index in range(4):
            active.enter_context((first if index % 2 else second).instance())
        with pytest.raises(ResourceBusy, match="instance limit"):
            with Coordinator(tmp_path).instance():
                pytest.fail("Capacity must reject immediately")
        # A distinct app state is explicitly a distinct admission scope.
        with Coordinator(tmp_path / "other").instance():
            pass
    with second.instance():
        pass


def test_instance_releases_after_failed_initialization(tmp_path):
    coordinator = Coordinator(tmp_path)
    with pytest.raises(RuntimeError, match="synthetic initialization"):
        with coordinator.instance():
            raise RuntimeError("synthetic initialization failure")
    with ExitStack() as active:
        for _ in range(4):
            active.enter_context(coordinator.instance())
