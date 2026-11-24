"""A story's `Base:` line (Michael with Pax, 2026-11-24).

Stories that build on each other share one feature branch, so each builder starts from it and
opens its pull request into it, and the chain moves without waiting for merges into the default
branch. The line is in the body the dispatch pinned; with none, the base is the repo's."""

from __future__ import annotations

import contextlib
import io
import subprocess
import unittest

from test_worker_story import BRANCH, StoryRig
from worker_support import git, worker

FEATURE = "feature/chain"


class AStoryOnItsChainsFeatureBranch(unittest.TestCase):
    def setUp(self):
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)
        self.s = StoryRig(self)
        # The chain's feature branch: main plus the work of the story before this one.
        git("checkout", "-q", "-b", FEATURE, cwd=self.s.seed)
        (self.s.seed / "EARLIER.txt").write_text("the story before this one\n")
        git("add", "EARLIER.txt", cwd=self.s.seed)
        git("commit", "-q", "-m", "the earlier story", cwd=self.s.seed)
        git("push", "-q", str(self.s.rig.origin), FEATURE, cwd=self.s.seed)
        self.earlier = git("rev-parse", "HEAD", cwd=self.s.seed).strip()

    def body(self, base: str = FEATURE) -> str:
        return f"Base: {base}\nBuilds on: acme#1\n\nApply add-widget."

    def test_the_story_starts_from_its_base_and_its_draft_goes_into_it(self):
        n = self.s.story(self.body())
        outcome = self.s.run("--no-pr", "--tick", "3", story=self.s.build("pass"))
        self.assertEqual(outcome.code, worker.HANDED_BACK, outcome.summary)
        head = self.s.origin_head(BRANCH)
        held = subprocess.run(
            ["git", "merge-base", "--is-ancestor", self.earlier, head], cwd=self.s.rig.origin
        )
        self.assertEqual(0, held.returncode, "the story branch does not hold its base's work")
        (pr,) = [p for p in self.s.rig.gh()["prs"] if p["headRefName"] == BRANCH]
        self.assertEqual(FEATURE, pr["baseRefName"])
        self.assertIn(f"against {FEATURE}", self.s.rig.prompt(n))

    def test_a_base_that_is_not_on_origin_is_handed_back_before_the_agent_starts(self):
        n = self.s.story(self.body("feature/nowhere"))
        outcome = self.s.run("--no-pr", "--tick", "3", story=self.s.build("pass"))
        self.assertIn(outcome.code, (worker.ERROR, worker.NOT_HANDED_BACK), outcome.summary)
        self.assertIn("base branch feature/nowhere is not on origin", outcome.summary)
        self.assertFalse((self.s.rig.record / f"prompt-{n}.md").exists(), "the agent ran")

    def test_a_base_that_is_not_a_plain_branch_name_is_refused(self):
        for bad in ("-x", "a..b", "feature/x;rm"):
            with self.subTest(base=bad):
                self.assertIsNone(worker.story_base({"title": "t", "body": f"Base: {bad}\n"}))

    def test_no_base_line_is_the_repos_base(self):
        self.assertIsNone(worker.story_base({"title": "t", "body": "Apply it."}))
        self.assertEqual(
            FEATURE, worker.story_base({"title": "t", "body": f"x\nBase: {FEATURE}\ny"})
        )


if __name__ == "__main__":
    unittest.main()
