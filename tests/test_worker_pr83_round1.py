"""Fix round 1 of PR #83's review (ledger item 1843): the guards the review found unheld.

- `own_problem` takes only the item's own branch, whole: not another item's whose number starts
  with this one's, and not one with a suffix after the stamp.
- `VERDICT` takes only the template's forms, each the whole line, a subset of the router's.
- On a PR's own branch the evidence is judged on THIS run: pushed past the cut, exit 0.
- A kept tree's unpushed commits are named in the hand-back, never pushed.
- A story whose ready PR cannot be made a draft says so, and not `(open, draft)`.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import unittest
from unittest import mock

import test_worker_one_item as one
from test_worker_story import BRANCH, StoryRig
from worker_support import git, worker

# What the router accepts (ikigraph artifacts/dax/item_flow.py and dax_route.py), with re.M.
ROUTER = re.compile(r"^REVIEW: (clean|red (\d+)|blocking \d+|unverified)\b", re.M)


class OwnBranchIsTheItemsWhole(unittest.TestCase):
    def test_another_items_branch_is_refused(self):
        for branch in ("worker/item-12-20261124T013016", "worker/item-12.2-20261124T013016"):
            with self.subTest(branch=branch):
                self.assertIsNotNone(worker.own_problem({"headRefName": branch}, 1))

    def test_a_branch_with_a_suffix_is_refused(self):
        for branch in (
            "worker/item-1-20261124T013016-x",
            "worker/item-1-20261124T013016/more",
            "worker/item-1-20261124T0130160",
            "worker/item-1-20261124T013016\n",
        ):
            with self.subTest(branch=branch):
                self.assertIsNotNone(worker.own_problem({"headRefName": branch}, 1))

    def test_the_items_own_branch_is_taken(self):
        for branch in ("worker/item-1-20261124T013016", "worker/item-1.3-20261124T013016"):
            with self.subTest(branch=branch):
                self.assertIsNone(worker.own_problem({"headRefName": branch}, 1))


class AVerdictIsTheTemplatesForm(unittest.TestCase):
    ACCEPTED = (
        "REVIEW: clean",
        "REVIEW: red 3",
        "REVIEW: red 12",
        "REVIEW: blocking 2",
        "REVIEW: unverified no build agent",
        "REVIEW: unverified x",
        "REVIEW: clean  ",
    )
    REFUSED = (
        "REVIEW: unverified",
        "REVIEW: unverified ",
        "REVIEW: clean-ish",
        "REVIEW: clean, mostly",
        "REVIEW: red 3.5",
        "REVIEW: red",
        "REVIEW: red three",
        "REVIEW: blocking 2 of 5",
        "REVIEW: blocking",
        "REVIEW: unverifiedness",
        "REVIEW: green",
        "review: clean",
        " REVIEW: clean",
    )

    def test_the_templates_forms_are_accepted(self):
        for line in self.ACCEPTED:
            with self.subTest(line=line):
                self.assertTrue(worker.VERDICT.match(line))

    def test_other_forms_are_refused(self):
        for line in self.REFUSED:
            with self.subTest(line=line):
                self.assertIsNone(worker.VERDICT.match(line))

    def test_every_accepted_line_is_one_the_router_reads(self):
        for line in self.ACCEPTED:
            with self.subTest(line=line):
                self.assertTrue(ROUTER.search(line))


class OwnBranchThisRun(one.AFixOnThePullRequestsOwnBranch):
    test_the_fix_is_pushed_onto_the_pull_requests_own_branch = None
    test_a_draft_note_on_its_own_branch_is_the_same = None
    test_the_brief_says_push_to_that_branch_and_open_no_pull_request = None
    test_a_pull_request_on_another_items_branch_is_not_continued = None
    test_continue_draft_pr_alone_still_stacks = None

    def test_a_push_by_an_agent_that_failed_is_not_evidence(self):
        n, branch = self.item_with_pr(self.NOTE)
        self.rig.agent_flags = ["--push-only", "--exit", "1"]
        outcome = self.run_it()
        self.assertNotEqual(git("rev-parse", branch, cwd=self.rig.origin).strip(), self.first)
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertEqual([], one.evidence_comments(self.ledger.items[n]))
        self.assertIn("failed after pushing to", outcome.summary)

    def test_an_agent_that_pushed_nothing_is_told_so(self):
        n, branch = self.item_with_pr(self.NOTE)
        self.rig.agent_flags = ["--no-pr"]
        outcome = self.run_it()
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn(f"pushed nothing new to {branch}", outcome.summary)

    def test_a_pr_closed_during_the_run_is_not_evidence(self):
        n, branch = self.item_with_pr(self.NOTE)
        close = worker.GitHub.pull_requests

        def closed(gh, *a, **k):
            prs, err = close(gh, *a, **k)
            for p in prs:
                p.state = "CLOSED"
            return prs, err

        self.rig.agent_flags = ["--push-only"]
        with mock.patch.object(worker.GitHub, "pull_requests", closed):
            outcome = self.run_it()
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn("is no longer open", outcome.summary)

    def test_a_kept_trees_dropped_commit_is_named_in_the_hand_back(self):
        n = self.ledger.file("Fix the due dates", ["worker:w1", "repo:lib"], body=self.NOTE)
        self.rig.configure()
        w = self.rig.worker(self.ledger)
        kept = worker.make_workspace(w.root, w.wc.repos["lib"], n)
        git("push", "-q", "origin", f"HEAD:refs/heads/{kept.branch}", cwd=kept.path)
        pushed = git("rev-parse", "HEAD", cwd=kept.path).strip()
        (kept.path / "HALF.txt").write_text("half\n")
        git("add", "HALF.txt", cwd=kept.path)
        git("commit", "-q", "-m", "half done", cwd=kept.path)
        half = git("rev-parse", "HEAD", cwd=kept.path).strip()
        pr = {
            "number": 1,
            "url": one.PR1,
            "state": "OPEN",
            "headRefName": kept.branch,
            "headRefOid": pushed,
            "baseRefName": "main",
            "isDraft": True,
            "isCrossRepository": False,
        }
        self.rig.gh_state.write_text(json.dumps({"slug": "acme/lib", "prs": [pr]}))
        self.rig.agent_flags = ["--push-only"]
        self.rig.configure()
        outcome = self.rig.worker(self.ledger).run_once()
        self.assertEqual(outcome.code, worker.HANDED_BACK, outcome.summary)
        head = git("rev-parse", kept.branch, cwd=self.rig.origin).strip()
        self.assertEqual(git("rev-parse", f"{head}~1", cwd=self.rig.origin).strip(), pushed)
        [comment] = one.evidence_comments(self.ledger.items[n])
        self.assertIn(f"up to {half}", comment)
        self.assertIn("not pushed onto the pull request", comment)


class AStoryThatStaysReady(unittest.TestCase):
    def setUp(self):
        self.s = StoryRig(self)
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def test_the_release_says_the_pr_is_still_ready_and_why(self):
        create = worker.GitHub.create_draft

        def opened_ready(gh, *a, **k):
            done = create(gh, *a, **k)
            state = self.s.rig.gh()
            for pr in state["prs"]:
                pr["isDraft"] = False
            state["ready"] = "refused"
            self.s.rig.gh_state.write_text(json.dumps(state))
            return done

        n = self.s.story()
        with mock.patch.object(worker.GitHub, "create_draft", opened_ready):
            outcome = self.s.run("--no-pr", "--tick", "3", story=self.s.build("pass"))
        (pr,) = [p for p in self.s.rig.gh()["prs"] if p["headRefName"] == BRANCH]
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn("could not be made a draft", outcome.summary)
        said = "\n".join(c["text"] for c in self.s.ledger.human_comments(n))
        self.assertIn(f"{pr['url']} is still ready", said)
        self.assertIn("making it a draft failed: GraphQL", said)
        self.assertIn(f"{pr['url']} (open): CI", said)


if __name__ == "__main__":
    unittest.main()
