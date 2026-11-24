"""Review of PR #83 (carducci#1839, round 1a): one item per piece of work, the worker's half.

Each test fails at ad5a4813b67d for the defect its docstring names.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest import mock

import test_worker_one_item as one
from test_worker_story import BRANCH, StoryRig
from worker_support import git, worker


class OwnBranchHandBack(one.AFixOnThePullRequestsOwnBranch):
    # Only the tests below run from this class, not the inherited ones a second time.
    test_the_fix_is_pushed_onto_the_pull_requests_own_branch = None
    test_a_draft_note_on_its_own_branch_is_the_same = None
    test_the_brief_says_push_to_that_branch_and_open_no_pull_request = None
    test_a_pull_request_on_another_items_branch_is_not_continued = None
    test_continue_draft_pr_alone_still_stacks = None

    def test_an_agent_that_did_nothing_is_not_handed_back_with_the_old_pr(self):
        """On its own branch, the earlier run's PR is listed for the branch whatever the agent
        did, so an agent that pushed nothing, wrote no report and failed is handed back with
        that PR as evidence: the worker's no-evidence fence never fires."""
        n, branch = self.item_with_pr(self.NOTE)
        self.rig.agent_flags = ["--no-pr", "--exit", "1"]
        outcome = self.run_it()
        self.assertEqual(git("rev-parse", branch, cwd=self.rig.origin).strip(), self.first)
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertEqual([], one.evidence_comments(self.ledger.items[n]))

    def test_the_evidence_is_the_pr_the_brief_named(self):
        """The evidence is prs[0] of every PR ever opened on the branch, sorted by number: an
        older closed PR on the same branch is handed back instead of the open one named."""
        n, branch = self.item_with_pr(self.NOTE.replace("#1", "#2"))
        state = self.rig.gh()
        old = dict(state["prs"][0], state="CLOSED")
        new = dict(state["prs"][0], number=2, url="https://github.com/acme/lib/pull/2")
        state["prs"] = [old, new]
        self.rig.gh_state.write_text(json.dumps(state))
        self.rig.agent_flags = ["--push-only"]
        outcome = self.run_it()
        self.assertEqual(outcome.code, worker.HANDED_BACK, outcome.summary)
        [comment] = one.evidence_comments(self.ledger.items[n])
        self.assertTrue(comment.startswith(f"Evidence: {new['url']}\n"), comment)
        self.assertNotIn(f"Evidence: {one.PR1}\n", comment)


    def test_a_kept_trees_unpushed_commits_are_not_pushed_onto_the_pr(self):
        """`own` runs drop_own_trees for a task item, which pushes each kept worktree's HEAD to
        its branch before the agent starts: commits an earlier run of the item made and never
        pushed (it was stopped, or handed back without evidence) land on the item's evidence
        PR, pushed by the worker, unseen by any agent of this run."""
        n = self.ledger.file("Fix the due dates", ["worker:w1", "repo:lib"], body=self.NOTE)
        self.rig.configure()
        w = self.rig.worker(self.ledger)
        kept = worker.make_workspace(w.root, w.wc.repos["lib"], n)  # the earlier run's tree
        git("push", "-q", "origin", f"HEAD:refs/heads/{kept.branch}", cwd=kept.path)
        pushed = git("rev-parse", "HEAD", cwd=kept.path).strip()
        (kept.path / "HALF.txt").write_text("a stopped run's half-done work\n")
        git("add", "HALF.txt", cwd=kept.path)
        git("commit", "-q", "-m", "half done, never pushed", cwd=kept.path)
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
        self.rig.agent_flags = ["--no-pr", "--report", f"{one.PR1}\nNothing to do.\n"]
        self.rig.configure()
        self.rig.worker(self.ledger).run_once()
        self.assertEqual(git("rev-parse", kept.branch, cwd=self.rig.origin).strip(), pushed)


class AStoryHandedBackIsADraft(unittest.TestCase):
    def setUp(self):
        self.s = StoryRig(self)
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def test_a_ready_pr_that_cannot_be_made_a_draft_is_not_handed_back(self):
        """Spec (worker-story, Only a passing story is done): handed back with evidence, its
        pull request MUST still be a draft. When `gh pr ready --undo` fails, the story is still
        handed back as done, its PR ready, and the hand-back lists it as `(open, draft)`."""
        create = worker.GitHub.create_draft

        def opened_ready(gh, *a, **k):  # the agent (or an earlier run) marked it ready
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
        if outcome.code == worker.HANDED_BACK:
            self.assertTrue(pr["isDraft"], "handed back as done with its pull request ready")
        said = "\n".join(c["text"] for c in self.s.ledger.human_comments(n))
        self.assertNotIn(f"{pr['url']} (open, draft)", said)


if __name__ == "__main__":
    unittest.main()
