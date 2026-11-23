#!/usr/bin/env python3
"""A fake build and test command for the worker's story tests, as `[story] build` runs it.

    fake_build.py [--status pass|fail|none|garbled] [--exit N]

It prints a few lines of build output, then `AGENT-BUILD-RESULT {"status": …}` (none: no such
line; garbled: a line that is not JSON), and exits N (default 0).
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--status", default="pass")
    p.add_argument("--exit", type=int, default=0)
    args = p.parse_args()
    print("compiling 3 modules")
    print("running 12 tests")
    if args.status == "garbled":
        print("AGENT-BUILD-RESULT {not json")
    elif args.status != "none":
        print("AGENT-BUILD-RESULT " + json.dumps({"status": args.status, "tests": 12}))
    return args.exit


if __name__ == "__main__":
    sys.exit(main())
