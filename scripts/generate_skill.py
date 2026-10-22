"""Generate the stable packaged bootstrap from the canonical app-owned source."""

from pathlib import Path

from eplan_mcp.guidance import BOOTSTRAP

if __name__ == "__main__":
    path = Path(__file__).resolve().parents[1] / "plugins/eplan/skills/eplan-analysis/SKILL.md"
    path.write_text(BOOTSTRAP, encoding="utf-8", newline="\n")
