#!/usr/bin/env python3
"""The review's tests are the reviewer's (review-once D3; ported from ikigraph's
tools/review_tests.py on 2026-11-07, ledger item 1373): every test file the reviewer's commits on
`review/pr-<n>` added or changed must be byte for byte the same at the head.

    python3 tools/review_tests.py check --review <ref> --base <ref> [--head HEAD] [--repo DIR]

The reviewer's commits are those on `<review>` and not on `<base>` whose author email is
`.gonk/risk.toml`'s `reviewer_email`; their files under `tests` globs are compared. risk.toml is
read at `<base>`, so a change can't loosen the check on itself. No review branch
(the ref doesn't resolve) is a pass: a clean review pushes none. Exit 1 names each file that differs
or is gone at the head; exit 2 is a refusal (no risk.toml, no reviewer_email, a git error).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from risk import Refusal, loads  # noqa: E402


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True)


def resolves(repo: Path, ref: str) -> bool:
    return git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def blob(repo: Path, ref: str, path: str) -> bytes | None:
    p = git(repo, "show", f"{ref}:{path}")
    return p.stdout if p.returncode == 0 else None


def reviewer_files(repo: Path, review: str, base: str, email: str) -> list[str]:
    p = git(
        repo, "log", f"{base}..{review}", f"--author=<{email}>", "--name-only", "-z", "--format="
    )
    if p.returncode != 0:
        raise Refusal(f"git log {base}..{review}: {p.stderr.decode(errors='replace').strip()}")
    names = [x.strip("\n") for x in p.stdout.decode("utf-8", "surrogateescape").split("\0")]
    return sorted({n for n in names if n})


def last_by(repo: Path, review: str, base: str, email: str, path: str) -> str:
    """The reviewer's own last commit to `path`: a later one by anyone else can't rewrite it."""
    who = f"--author=<{email}>"
    p = git(repo, "log", "-1", "--format=%H", who, f"{base}..{review}", "--", path)
    return p.stdout.decode().strip() or review


def check(repo: Path, review: str, base: str, head: str) -> int:
    for ref in (base, head):
        if not resolves(repo, ref):
            raise Refusal(f"{ref} doesn't resolve to a commit")
    if not resolves(repo, review):
        print(f"review-tests: no {review}; nothing to check")
        return 0
    # The base's risk.toml, not the head's: a change can't loosen the check on itself.
    text = blob(repo, base, ".gonk/risk.toml")
    if text is None:
        raise Refusal(f"{base} has no .gonk/risk.toml; a review can't pick its depth without it")
    try:
        risk = loads(text.decode("utf-8"), f"{base}:.gonk/risk.toml")
    except UnicodeDecodeError:
        raise Refusal(f"{base}:.gonk/risk.toml is not UTF-8") from None
    if not risk.reviewer_email:
        raise Refusal(
            ".gonk/risk.toml has no reviewer_email: the reviewer's commits can't be told apart"
        )
    files = [f for f in reviewer_files(repo, review, base, risk.reviewer_email) if risk.is_test(f)]
    bad = 0
    for f in files:
        theirs = blob(repo, last_by(repo, review, base, risk.reviewer_email, f), f)
        if theirs is None:
            continue  # the reviewer's last commit removed it: nothing of theirs to keep
        if blob(repo, head, f) != theirs:
            print(f"review-tests: {f} differs from {review}")
            bad += 1
    if bad:
        print(
            f"review-tests: {bad} of the review's {len(files)} test file(s) changed; "
            "make the tests pass as written, or refute one on the task's ledger item"
        )
        return 1
    print(f"review-tests: the review's {len(files)} test file(s) are unchanged")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="review_tests.py", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--review", required=True)
    c.add_argument("--base", required=True)
    c.add_argument("--head", default="HEAD")
    c.add_argument("--repo", default=".")
    args = p.parse_args(argv)
    try:
        return check(Path(args.repo), args.review, args.base, args.head)
    except Refusal as e:
        print(f"review_tests.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
