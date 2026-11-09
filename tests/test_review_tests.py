"""review-once: risk classes by path, and the review's tests unchanged (ported from ikigraph's
tests/test_review_once.py on 2026-11-07, ledger item 1373).

Each test names the scenario of openspec/changes/review-once it pins.
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

RISK = """tests = ["tests/*"]
reviewer_email = "reviewer@tamariz.invalid"
[[path]]
glob = "worker/src/auth/*"
class = "a"
why = "auth"
[[path]]
glob = "artifacts/team/*"
class = "c"
why = "tooling"
"""


def repo_with(risk_toml: str | None) -> tempfile.TemporaryDirectory:
    d = tempfile.TemporaryDirectory()
    if risk_toml is not None:
        (Path(d.name) / ".gonk").mkdir()
        (Path(d.name) / ".gonk" / "risk.toml").write_text(risk_toml)
    return d


class RiskClasses(unittest.TestCase):
    def setUp(self):
        self.d = repo_with(RISK)
        self.addCleanup(self.d.cleanup)
        self.risk = risk.load(Path(self.d.name))

    def test_a_class_c_change(self):
        self.assertEqual("c", self.risk.diff(["artifacts/team/resource_map.py"]))

    def test_a_class_a_change(self):
        self.assertEqual("a", self.risk.diff(["worker/src/auth/grant-lifetime.ts", "README.md"]))

    def test_an_unlisted_path(self):
        self.assertEqual(("b", None), self.risk.of("src/main.rs"))

    def test_the_first_match_decides(self):
        d = repo_with(
            '[[path]]\nglob = "a/*"\nclass = "c"\n[[path]]\nglob = "a/b/*"\nclass = "a"\n'
        )
        self.addCleanup(d.cleanup)
        self.assertEqual("c", risk.load(Path(d.name)).of("a/b/x")[0])

    def test_a_missing_or_bad_file_is_refused_naming_it(self):
        for text, says in (
            (None, "missing"),
            ("x = [", "can't read"),
            ('[[path]]\nclass = "a"\n', "has no glob"),
            ('[[path]]\nglob = "x"\nclass = "d"\n', "not a, b or c"),
            ('tests = "tests/*"\n', "tests is not a list"),
        ):
            d = repo_with(text)
            self.addCleanup(d.cleanup)
            with self.assertRaises(risk.Refusal) as e:
                risk.load(Path(d.name))
            self.assertIn(says, str(e.exception))
            self.assertIn("risk.toml", str(e.exception))

    def test_the_starters_own_classes(self):
        own = risk.load(ROOT)
        self.assertEqual("a", own.of(".github/workflows/ci.yml")[0])
        self.assertEqual("a", own.of(".gonk/risk.toml")[0])
        self.assertEqual("b", own.of("tools/worker.py")[0])
        self.assertTrue(own.reviewer_email)


class ReviewTests(unittest.TestCase):
    """A real git repository: main, the worker's PR head, the reviewer's branch, the fix."""

    def git(self, *args, author="worker@tamariz.invalid"):
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "x",
            "GIT_AUTHOR_EMAIL": author,
            "GIT_COMMITTER_NAME": "x",
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

    def commit(self, msg, author="worker@tamariz.invalid"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg, author=author)

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup)
        self.r = Path(self.d.name)
        self.git("init", "-q", "-b", "main")
        self.write(".gonk/risk.toml", RISK)
        self.write("tests/test_old.py", "old\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "pr")
        self.write("tests/test_worker.py", "worker's own test\n")
        self.commit("the change")
        self.git("checkout", "-q", "-b", "review/pr-7")
        self.write("tests/test_review.py", "assert where != ''\n")
        self.commit("review: an empty --where loads", author="reviewer@tamariz.invalid")
        self.git("checkout", "-q", "pr")
        self.git("merge", "-q", "--no-edit", "review/pr-7")

    def check(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = review_tests.check(self.r, "review/pr-7", "main", "HEAD")
        return code, out.getvalue()

    def test_the_fix_makes_the_tests_pass(self):
        self.write("src.py", "fixed\n")
        self.write("tests/test_worker.py", "the worker may change its own test\n")
        self.commit("fix")
        code, out = self.check()
        self.assertEqual(0, code, out)
        self.assertIn("the review's 1 test file(s) are unchanged", out)

    def test_the_fix_edits_a_review_test(self):
        self.write("tests/test_review.py", "assert True\n")
        self.commit("fix")
        code, out = self.check()
        self.assertEqual(1, code)
        self.assertIn("review-tests: tests/test_review.py differs from review/pr-7\n", out)

    def test_the_fix_deletes_a_review_test(self):
        (self.r / "tests" / "test_review.py").unlink()
        self.commit("fix")
        self.assertEqual(1, self.check()[0])

    def test_no_review_branch_is_a_pass(self):
        self.git("branch", "-q", "-D", "review/pr-7")
        code, out = self.check()
        self.assertEqual(0, code)
        self.assertIn("no review/pr-7", out)

    def test_an_older_review_merged_into_main_is_not_this_ones(self):
        # A reviewer commit already on main (an earlier PR's review) is not compared.
        self.git("checkout", "-q", "main")
        self.write("tests/test_earlier.py", "earlier review\n")
        self.commit("earlier review", author="reviewer@tamariz.invalid")
        self.git("checkout", "-q", "pr")
        self.write("tests/test_earlier.py", "changed later\n")
        self.commit("fix")
        self.assertEqual(0, self.check()[0])

    def test_the_head_cant_loosen_the_check(self):
        # risk.toml is read at the base: a fix that drops the tests glob is still checked.
        self.write(".gonk/risk.toml", 'reviewer_email = "reviewer@tamariz.invalid"\ntests = []\n')
        self.write("tests/test_review.py", "assert True\n")
        self.commit("fix")
        self.assertEqual(1, self.check()[0])

    def test_no_reviewer_email_on_the_base_is_refused(self):
        self.git("checkout", "-q", "main")
        self.write(".gonk/risk.toml", 'tests = ["tests/*"]\n')
        self.commit("drop the email")
        self.git("checkout", "-q", "pr")
        with self.assertRaises(risk.Refusal):
            review_tests.check(self.r, "review/pr-7", "main", "HEAD")


if __name__ == "__main__":
    unittest.main()
