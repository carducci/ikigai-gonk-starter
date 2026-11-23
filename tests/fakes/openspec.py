#!/usr/bin/env python3
"""A fake `openspec` for the worker's story tests: only `openspec validate <id> --strict`.

The change is valid when `openspec/changes/<id>/proposal.md` exists in the working directory and
the environment does not say `FAKE_OPENSPEC=fail`. tests/test_worker_story.py puts it on PATH as
`openspec`, through a wrapper it writes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    argv = sys.argv[1:]
    if len(argv) != 3 or argv[0] != "validate" or argv[2] != "--strict":
        print(f"fake openspec: not a call the worker makes: {argv}", file=sys.stderr)
        return 2
    change = argv[1]
    proposal = Path("openspec") / "changes" / change / "proposal.md"
    if proposal.is_file() and os.environ.get("FAKE_OPENSPEC") != "fail":
        print(f"Change '{change}' is valid")
        return 0
    print(f"Change '{change}' has issues")
    print("✗ [ERROR] proposal.md: missing or invalid")
    return 1


if __name__ == "__main__":
    sys.exit(main())
