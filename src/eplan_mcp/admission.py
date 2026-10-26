"""Independent finite budgets for chat metadata and lazily acquired analysis."""

METADATA_FRONTDOORS = 20
METADATA_PROCESS_BYTES = 128 * 1024 * 1024
OWNER_TREE_PROCESSES = 12
OWNER_TREE_BYTES = 768 * 1024 * 1024
ANALYSIS_OPERATIONS = 4


def app_envelope(frontdoors, analysis):
    """App-owned actors/commit only; SDK helpers and legacy generations are separate."""
    analysis = min(frontdoors, analysis, ANALYSIS_OPERATIONS)
    return {
        "frontdoors": frontdoors,
        "analysis": analysis,
        "processes": frontdoors + analysis * (OWNER_TREE_PROCESSES - 1),
        "private_commit_bytes": (frontdoors - analysis) * METADATA_PROCESS_BYTES
        + analysis * OWNER_TREE_BYTES,
    }
