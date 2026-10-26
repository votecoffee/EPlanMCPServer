"""Explicit SOURCE-ONLY packed layout preparation; never selects or serves it."""

import argparse
import json
from pathlib import Path

from eplan_mcp.packed_runtime import REVIEWED_FAMILIES, build_layout, decode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    inventory = decode(args.inventory.read_bytes())
    print(
        json.dumps(
            build_layout(
                args.source, args.destination, inventory["files"], reviewed_families=REVIEWED_FAMILIES
            )
        )
    )


if __name__ == "__main__":
    main()
