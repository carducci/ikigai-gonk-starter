#!/usr/bin/env python3
"""A fake coding agent for the worker's tests. It runs in the item's worktree, as a real one
would, and does what its flags say: record its brief, sleep, edit a file, commit, push the
branch and "open a pull request" through the stub gh, or report evidence without one.

    fake_agent.py --record <dir> --gh "<argv of the stub gh>" --branch B --item N
                  [--sleep S] [--no-pr] [--evidence URL --report-file P] [--report TEXT]
                  [--report-hex HEX] [--say TEXT] [--chatter TEXT] [--exit N] -- <prompt>
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time
from pathlib import Path


def git(*argv: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=fake agent", "-c", "user.email=agent@example.invalid", *argv],
        check=True,
        capture_output=True,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--record", required=True)
    p.add_argument("--gh", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--item", required=True)
    p.add_argument("--sleep", type=float, default=0)
    p.add_argument("--no-pr", action="store_true")
    p.add_argument("--evidence")
    p.add_argument("--report-file")
    p.add_argument("--report", help="text for the report file, whether or not it opens a PR")
    p.add_argument("--report-hex", help="bytes for the report file, in hex: not always UTF-8")
    p.add_argument("--say", help="its final message, on stdout, as `claude -p` prints one")
    p.add_argument("--chatter", help="progress on stderr, as `codex exec` writes it")
    p.add_argument("--exit", type=int, default=0)
    p.add_argument("prompt")
    args = p.parse_args()

    record = Path(args.record)
    record.mkdir(parents=True, exist_ok=True)
    (record / f"prompt-{args.item}.md").write_text(args.prompt)
    (record / f"cwd-{args.item}").write_text(str(Path.cwd()))
    (record / f"started-{args.item}").write_text(str(time.time()))
    time.sleep(args.sleep)

    if args.chatter:
        print(args.chatter, file=sys.stderr, flush=True)
    if args.evidence:
        Path(args.report_file).write_text(f"{args.evidence}\nIt does not reproduce: see the run.\n")
    if args.report is not None:
        Path(args.report_file).write_text(args.report)
    if args.report_hex is not None:
        Path(args.report_file).write_bytes(bytes.fromhex(args.report_hex))
    if not args.no_pr:
        Path("WORKED.txt").write_text(f"item {args.item}\n")
        git("add", "WORKED.txt")
        git("commit", "-q", "-m", f"Work on item {args.item}")
        git("push", "-q", "origin", f"HEAD:refs/heads/{args.branch}")
        gh = shlex.split(args.gh)
        subprocess.run(
            [*gh, "pr", "create", "--head", args.branch, "--title", f"item {args.item}"],
            check=True,
            capture_output=True,
        )
    if args.say:
        print(args.say)
    (record / f"finished-{args.item}").write_text(str(time.time()))
    return args.exit


if __name__ == "__main__":
    sys.exit(main())
