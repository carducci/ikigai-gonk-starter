#!/usr/bin/env python3
"""A path's risk class, from the repository's `.gonk/risk.toml` (review-once D5; ported from
ikigraph's artifacts/team/review/risk.py on 2026-11-07, ledger item 1373). The class sets how hard
a review attacks a change and how many reviews it gets: `a` two, `b` and `c` one.

    python3 tools/risk.py class <path>...        each path's class and the rule
    python3 tools/risk.py diff <base> [<head>]   the class of the diff (the highest)
        [--repo DIR]                                             the repository (default: here)

`.gonk/risk.toml`:

    tests = ["tests/*"]                        # where review tests go (review_tests.py)
    reviewer_email = "reviewer@tamariz.invalid"  # the reviewer's commits, by author
    [[path]]
    glob = "hooks/claude/*"                    # fnmatch: `*` crosses `/`
    class = "a"
    why = "the claim guard"

The first glob that matches decides; a path no glob matches is `b`. A missing or unreadable file, or
a rule without a glob or with another class, is refused, naming it: a class is never guessed.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

CLASSES = ("a", "b", "c")
DEFAULT = "b"
RANK = {"c": 0, "b": 1, "a": 2}


class Refusal(Exception):
    pass


@dataclass
class Rule:
    glob: str
    cls: str
    why: str


@dataclass
class Risk:
    rules: list[Rule]
    tests: list[str]
    reviewer_email: str | None

    def of(self, path: str) -> tuple[str, Rule | None]:
        for rule in self.rules:
            if fnmatch.fnmatchcase(path, rule.glob):
                return rule.cls, rule
        return DEFAULT, None

    def diff(self, paths: list[str]) -> str:
        return max((self.of(p)[0] for p in paths), key=RANK.__getitem__, default="c")

    def is_test(self, path: str) -> bool:
        return any(fnmatch.fnmatchcase(path, g) for g in self.tests)


def load(repo: Path) -> Risk:
    f = repo / ".gonk" / "risk.toml"
    try:
        text = f.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise Refusal(f"{f}: missing; a review can't pick its depth without it") from None
    except (OSError, UnicodeDecodeError) as e:
        raise Refusal(f"{f}: can't read it ({e})") from None
    return loads(text, str(f))


def loads(text: str, f: str = ".gonk/risk.toml") -> Risk:
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise Refusal(f"{f}: can't read it ({e})") from None
    rules = []
    for n, r in enumerate(doc.get("path", []), 1):
        if not isinstance(r, dict) or not isinstance(r.get("glob"), str) or not r["glob"]:
            raise Refusal(f"{f}: [[path]] {n} has no glob")
        if r.get("class") not in CLASSES:
            raise Refusal(
                f"{f}: [[path]] {n} ({r['glob']}) has class {r.get('class')!r}, not a, b or c"
            )
        rules.append(Rule(r["glob"], r["class"], str(r.get("why", ""))))
    tests = doc.get("tests", [])
    if not isinstance(tests, list) or not all(isinstance(t, str) and t for t in tests):
        raise Refusal(f"{f}: tests is not a list of globs")
    email = doc.get("reviewer_email")
    if email is not None and (not isinstance(email, str) or "@" not in email):
        raise Refusal(f"{f}: reviewer_email is not an email address")
    return Risk(rules, tests, email)


def changed(repo: Path, base: str, head: str) -> list[str]:
    p = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only", "-z", f"{base}...{head}"],
        capture_output=True,
    )
    if p.returncode != 0:
        raise Refusal(f"git diff {base}...{head}: {p.stderr.decode(errors='replace').strip()}")
    return [x for x in p.stdout.decode("utf-8", "surrogateescape").split("\0") if x]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="risk.py", description=__doc__.splitlines()[0])
    p.add_argument("--repo", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("class")
    c.add_argument("paths", nargs="+")
    d = sub.add_parser("diff")
    d.add_argument("base")
    d.add_argument("head", nargs="?", default="HEAD")
    args = p.parse_args(argv)
    repo = Path(args.repo)
    try:
        risk = load(repo)
        if args.cmd == "class":
            for path in args.paths:
                cls, rule = risk.of(path)
                print(f"{cls} {path} ({rule.glob if rule else 'no glob: the default'})")
        else:
            paths = changed(repo, args.base, args.head)
            print(risk.diff(paths))
    except Refusal as e:
        print(f"risk.py: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
