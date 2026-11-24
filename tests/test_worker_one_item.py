"""One ledger item per piece of work (Michael, 2026-11-22: "Drain, then one lane at a time"):
review and fix are moves of the same item, not items of their own. The worker's side of it:

- `Continue PR #N on its own branch` in the brief: the fix lands on that PR's own branch, the
  one this item's earlier run opened, and the PR stays the item's one evidence. No stacked PR.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from worker_support import FakeLedger, Rig, git, worker

PR1 = "https://github.com/acme/lib/pull/1"


def evidence_comments(item: dict) -> list[str]:
    return [c["text"] for c in item["comments"] if c["text"].startswith("Evidence:")]


class AFixOnThePullRequestsOwnBranch(unittest.TestCase):
    def setUp(self):
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)
        self.ledger = FakeLedger()
        self.rig = Rig(self)

    def item_with_pr(self, body: str, branch_of=None):
        """An item whose earlier run opened draft PR #1 on its own worker branch."""
        n = self.ledger.file("Fix the due dates", ["worker:w1", "repo:lib"], body=body)
        branch = (branch_of or (lambda n: f"worker/item-{n}-20261123T101500"))(n)
        seed = self.rig.tmp / "earlier"
        git("clone", "-q", str(self.rig.origin), str(seed))
        git("checkout", "-q", "-b", branch, cwd=seed)
        (seed / "DUE.txt").write_text("the first run's work\n")
        git("add", "DUE.txt", cwd=seed)
        git("commit", "-q", "-m", "the first run", cwd=seed)
        git("push", "-q", "origin", branch, cwd=seed)
        self.first = git("rev-parse", "HEAD", cwd=seed).strip()
        pr = {
            "number": 1,
            "url": "https://github.com/acme/lib/pull/1",
            "state": "OPEN",
            "headRefName": branch,
            "headRefOid": self.first,
            "baseRefName": "main",
            "isDraft": True,
            "isCrossRepository": False,
        }
        self.rig.gh_state.write_text(json.dumps({"slug": "acme/lib", "prs": [pr]}))
        return n, branch

    def run_it(self):
        self.rig.configure()
        return self.rig.worker(self.ledger).run_once()

    NOTE = "Continue PR #1 on its own branch: make the review's tests pass, push, and hand back."

    def test_the_fix_is_pushed_onto_the_pull_requests_own_branch(self):
        n, branch = self.item_with_pr(self.NOTE)
        self.rig.agent_flags = ["--push-only"]
        outcome = self.run_it()
        self.assertEqual(outcome.code, worker.HANDED_BACK, outcome.summary)
        head = git("rev-parse", branch, cwd=self.rig.origin).strip()
        self.assertEqual(git("rev-parse", f"{head}~1", cwd=self.rig.origin).strip(), self.first)
        self.assertEqual([1], [pr["number"] for pr in self.rig.gh()["prs"]], "no new pull request")
        [comment] = evidence_comments(self.ledger.items[n])
        self.assertTrue(comment.startswith(f"Evidence: {PR1}\n"), comment)
        self.assertNotIn("stacked", comment)

    def test_a_draft_note_on_its_own_branch_is_the_same(self):
        n, branch = self.item_with_pr("Continue draft PR #1 on its own branch: fix it.")
        self.rig.agent_flags = ["--push-only"]
        self.assertEqual(self.run_it().code, worker.HANDED_BACK)
        self.assertNotEqual(git("rev-parse", branch, cwd=self.rig.origin).strip(), self.first)

    def test_the_brief_says_push_to_that_branch_and_open_no_pull_request(self):
        n, branch = self.item_with_pr(self.NOTE)
        self.rig.agent_flags = ["--push-only"]
        self.run_it()
        prompt = self.rig.prompt(n)
        self.assertIn(f"on the branch {branch}", prompt)
        self.assertIn(f"made for you from\n   origin/{branch}.", prompt)
        self.assertIn("open NO new pull request", prompt)
        self.assertIn("https://github.com/acme/lib/pull/1", prompt)

    def test_a_pull_request_on_another_items_branch_is_not_continued(self):
        for other in ("worker/item-9999-20261123T101500", "feature/someone-else", "story/x"):
            with self.subTest(branch=other):
                self.setUp()
                n, branch = self.item_with_pr(self.NOTE, branch_of=lambda n, b=other: b)
                outcome = self.run_it()
                self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
                self.assertIn("not this item's own branch", outcome.summary)
                self.assertEqual(git("rev-parse", branch, cwd=self.rig.origin).strip(), self.first)
                self.assertFalse((self.rig.record / f"prompt-{n}.md").exists(), "the agent ran")

    def test_continue_draft_pr_alone_still_stacks(self):
        n, branch = self.item_with_pr("Continue draft PR #1: answer the review.")
        self.rig.agent_flags = ["--draft-base", branch]
        self.assertEqual(self.run_it().code, worker.HANDED_BACK)
        self.assertEqual(git("rev-parse", branch, cwd=self.rig.origin).strip(), self.first)
        self.assertEqual([1, 2], [pr["number"] for pr in self.rig.gh()["prs"]])


if __name__ == "__main__":
    unittest.main()
