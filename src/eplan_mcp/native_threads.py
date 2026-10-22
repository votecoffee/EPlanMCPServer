"""Apply the standalone process's numerical pool policy before loading native libraries."""

import os
import sys

LIMITS = {
    name: "1"
    for name in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    )
}
_applied = False


def apply_before_import(environment=None, loaded_modules=None):
    """Not a library-host retuning API. Existing native pools must never be silently adopted."""
    global _applied
    target = os.environ if environment is None else environment
    modules = sys.modules if loaded_modules is None else loaded_modules
    if any(name in modules for name in ("numpy", "scipy", "ezdxf")):
        raise ValueError("Native pool policy requires a fresh standalone process before NumPy/ezdxf imports")
    target.update(LIMITS)
    if environment is None:
        _applied = True
    return dict(LIMITS)


def status():
    return {
        "policy": "one native numerical thread per standalone process",
        "applied_before_import": _applied,
        "configured_environment": {key: os.environ.get(key) for key in LIMITS},
        "native_pool_introspection": False,
    }
