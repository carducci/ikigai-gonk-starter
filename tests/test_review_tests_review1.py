"""Review 1 of PR 45 (ledger item 1373): the review-tests check against review branches as they
are really made. Each test fails at 81f3337 for the reason its docstring gives.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import review_tests  # noqa: E402
import risk  # noqa: E402

# The identity every agent commit in this repository carries, the reviewer's included: the
# commits on origin's review/pr-31 (55e59ff) and review/pr-37 (ffe9f06) are authored by it, and
# nothing in the starter (tools/worker.py push_review_branches, the review prompt) sets another.
AGENT = "345050139+carducci-agents@users.noreply.github.com"


class Repo(unittest.TestCase):
    def git(self, *args, author=AGENT):
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "carducci-agents",
            "GIT_AUTHOR_EMAIL": author,
            "GIT_COMMITTER_NAME": "carducci-agents",
            "GIT_COMMITTER_EMAIL": author,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        }
        p = subprocess.run(["git", *args], cwd=self.r, env=env, capture_output=True, text=True)
        self.assertEqual(0, p.returncode, p.stderr)
        return p.stdout

    def write(self, path, text):
        f = self.r / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    def commit(self, msg, author=AGENT):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg, author=author)

    def make(self, risk_toml: str, reviewer: str):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.r = Path(self.d.name)
        self.git("init", "-q", "-b", "main")
        self.write(".gonk/risk.toml", risk_toml)
        self.commit("base")
        self.git("checkout", "-q", "-b", "pr")
        self.write("src.py", "broken\n")
        self.commit("the change")
        self.git("checkout", "-q", "-b", "review/pr-7")
        self.write("tests/test_review.py", "assert fixed()\n")
        self.commit("review: a failing test", author=reviewer)
        self.git("checkout", "-q", "pr")
        self.git("merge", "-q", "--no-edit", "review/pr-7")

    def check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = review_tests.check(self.r, "review/pr-7", "main", "HEAD")
        return code, out.getvalue()


class ReviewTestsAsReallyMade(Repo):
    def test_a_review_commit_as_the_worker_makes_it_is_held(self):
        """With the starter's own .gonk/risk.toml, a reviewer's test committed as reviewers here
        really commit (the agents' account, not reviewer@tamariz.invalid) is not counted: the
        check reports 0 files and passes a head that rewrote the test."""
        self.make((ROOT / ".gonk" / "risk.toml").read_text(), reviewer=AGENT)
        self.write("tests/test_review.py", "assert True\n")
        self.commit("fix")
        code, out = self.check()
        self.assertEqual(1, code, out)

    def test_a_later_non_reviewer_commit_on_the_review_branch_cant_rewrite_the_test(self):
        """The head is compared with the review branch's tip, not with the reviewer's commits: a
        commit by anyone else on review/pr-<n> that weakens the reviewer's test (or deletes it)
        makes a head with the same weakened test pass."""
        self.make((ROOT / ".gonk" / "risk.toml").read_text(), reviewer="reviewer@tamariz.invalid")
        self.git("checkout", "-q", "review/pr-7")
        self.write("tests/test_review.py", "assert True\n")
        self.commit("tidy the review test", author="worker@tamariz.invalid")
        self.git("checkout", "-q", "pr")
        self.write("tests/test_review.py", "assert True\n")
        self.commit("fix")
        code, out = self.check()
        self.assertEqual(1, code, out)


class TheGateIsClassA(unittest.TestCase):
    def test_the_checks_own_code_is_class_a(self):
        """CI runs the pull request's own copy of tools/review_tests.py and tools/risk.py (a
        pull_request run checks out the merge commit), yet .gonk/risk.toml classes them c, one
        review: a fix round can loosen the check on itself with the lightest review."""
        own = risk.load(ROOT)
        for path in ("tools/review_tests.py", "tools/risk.py"):
            self.assertEqual("a", own.of(path)[0], path)


if __name__ == "__main__":
    unittest.main()
