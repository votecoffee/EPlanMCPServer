"""Pure environment/module-map tests; never initializes or retunes a native library."""

import pytest

from eplan_mcp.native_threads import LIMITS, apply_before_import


def test_fresh_standalone_limits_override_inherited_parallelism_only_locally():
    environment = {"OPENBLAS_NUM_THREADS": "64", "OMP_NUM_THREADS": "32", "PATH": "preserved"}
    assert apply_before_import(environment, {}) == LIMITS
    assert all(environment[key] == "1" for key in LIMITS)
    assert environment["PATH"] == "preserved"


@pytest.mark.parametrize("module", ["numpy", "scipy", "ezdxf"])
def test_preloaded_native_host_refused_without_environment_mutation(module):
    environment = {"OPENBLAS_NUM_THREADS": "64"}
    with pytest.raises(ValueError, match="fresh standalone"):
        apply_before_import(environment, {module: object()})
    assert environment == {"OPENBLAS_NUM_THREADS": "64"}


def test_policy_has_no_system_environment_or_clock_discovery():
    environment = {"EPLAN_MANAGEMENT_REGISTRY": "private", "EPLAN_MCP_CONFIG": "selected"}
    apply_before_import(environment, {})
    assert environment["EPLAN_MANAGEMENT_REGISTRY"] == "private"
    assert environment["EPLAN_MCP_CONFIG"] == "selected"
