"""Review of PR #86 (ledger item 1853): a story's `Base:` line, on input the PR's tests leave out.

A body that says `Base: <branch>` must start the story from that branch and open its pull request
into it, or hand the story back. It must never quietly fall back to the repository's base, which
puts a chain's story into the default branch without the work it builds on."""

from __future__ import annotations

import contextlib
import io
import unittest

from test_worker_story import BRANCH, StoryRig
from worker_support import git

FEATURE = "feature/chain"


class ABaseLineTheWorkerMustNotIgnore(unittest.TestCase):
    def setUp(self):
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)
        self.s = StoryRig(self)
        git("checkout", "-q", "-b", FEATURE, cwd=self.s.seed)
        (self.s.seed / "EARLIER.txt").write_text("the story before this one\n")
        git("add", "EARLIER.txt", cwd=self.s.seed)
        git("commit", "-q", "-m", "the earlier story", cwd=self.s.seed)
        git("push", "-q", str(self.s.rig.origin), FEATURE, cwd=self.s.seed)

    def bases(self, body: str) -> tuple[int, list[str]]:
        n = self.s.story(body)
        self.s.run("--no-pr", "--tick", "3", story=self.s.build("pass"))
        prs = [p for p in self.s.rig.gh()["prs"] if p["headRefName"] == BRANCH]
        return n, [p["baseRefName"] for p in prs]

    def test_a_body_with_crlf_line_ends_still_starts_from_its_base(self):
        # A ledger body written by a client that ends lines with CRLF says the same thing.
        _, bases = self.bases(f"Base: {FEATURE}\r\nBuilds on: acme#1\r\n\r\nApply add-widget.")
        self.assertEqual([FEATURE], bases, "the Base line was ignored: the PR went elsewhere")

    def test_a_base_line_naming_no_usable_branch_opens_no_pr_into_the_default_branch(self):
        n, bases = self.bases(f"Base: {FEATURE};\n\nApply add-widget.")
        self.assertNotIn("main", bases, "a story that names a base was opened into main")
        self.assertFalse(
            (self.s.rig.record / f"prompt-{n}.md").exists(),
            "the agent ran from main although the body names another base",
        )

    def test_head_is_not_a_branch_to_open_a_pull_request_into(self):
        # `git check-ref-format --branch HEAD` refuses it; origin/HEAD exists in every clone.
        _, bases = self.bases("Base: HEAD\n\nApply add-widget.")
        self.assertNotIn("HEAD", bases, "a draft pull request was opened against `HEAD`")


if __name__ == "__main__":
    unittest.main()
