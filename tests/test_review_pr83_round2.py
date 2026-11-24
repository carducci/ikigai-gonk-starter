"""Review of PR #83 (carducci#1839, round 2): one item per piece of work, the worker's half.

Each test fails at dae57717b2ad for the defect its docstring names, and passes at the base
(tamariz-loops), where a brief's `Continue PR #N on its own branch` is not read.
"""

from __future__ import annotations

import json
import time
import unittest
from unittest import mock

import test_worker_one_item as one
from worker_support import git, worker


class OwnBranchRoundTwo(one.AFixOnThePullRequestsOwnBranch):
    # Only the tests below run from this class, not the inherited ones a second time.
    test_the_fix_is_pushed_onto_the_pull_requests_own_branch = None
    test_a_draft_note_on_its_own_branch_is_the_same = None
    test_the_brief_says_push_to_that_branch_and_open_no_pull_request = None
    test_a_pull_request_on_another_items_branch_is_not_continued = None
    test_continue_draft_pr_alone_still_stacks = None

    def watching(self, after):
        """Run `after()` once the agent has ended, inside the worker's watch."""
        watch = worker.Worker.watch

        def watched(w, *a, **k):
            ended = watch(w, *a, **k)
            after()
            return ended

        self.patch = mock.patch.object(worker.Worker, "watch", watched)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_someone_elses_push_during_the_run_is_not_this_runs_evidence(self):
        """branch_moved asks only whether origin's branch moved past the cut, not whether THIS
        run's agent moved it: an agent that did nothing (no commit, no push, no report) and
        exited 0 is handed back with the PR as evidence when anyone else pushed to the branch
        while it ran (a person, the router, a bot)."""
        n, branch = self.item_with_pr(self.NOTE)
        seed = self.rig.tmp / "earlier"
        self.rig.configure()
        source = self.rig.worker(self.ledger).root / "lib" / ".source"

        def someone_else_pushes():
            (seed / "OTHER.txt").write_text("not the agent's\n")
            git("add", "OTHER.txt", cwd=seed)
            git("commit", "-q", "-m", "someone else", cwd=seed)
            git("push", "-q", "origin", branch, cwd=seed)
            git("fetch", "-q", "origin", cwd=source)  # the agent pulls, to be up to date

        self.watching(someone_else_pushes)
        self.rig.agent_flags = ["--no-pr"]
        outcome = self.run_it()
        self.assertNotEqual(git("rev-parse", branch, cwd=self.rig.origin).strip(), self.first)
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertEqual([], one.evidence_comments(self.ledger.items[n]))

    def test_a_ready_pr_the_agent_opened_on_the_branch_is_made_a_draft(self):
        """On its own branch the worker keeps only the PR the brief named, so a PR the agent
        opened from the same branch against its rule (another base, ready for review) is
        dropped before ledger item 1143's guard: never made a draft, never named in the
        hand-back, and its merge never warned of."""
        n, branch = self.item_with_pr(self.NOTE)

        def agent_opens_a_ready_pr():
            heads = git(
                "for-each-ref", "--format=%(refname:short) %(subject)", "refs/heads/worker",
                cwd=self.rig.origin,
            )  # fmt: skip
            pushed = [ln.split()[0] for ln in heads.splitlines() if "Work on item" in ln]
            state = self.rig.gh()
            state["prs"].append(
                dict(
                    state["prs"][0],
                    number=2,
                    url="https://github.com/acme/lib/pull/2",
                    headRefName=pushed[0],
                    baseRefName="release",
                    isDraft=False,
                )
            )
            self.rig.gh_state.write_text(json.dumps(state))

        self.watching(agent_opens_a_ready_pr)
        self.rig.agent_flags = ["--push-only"]
        self.run_it()
        [second] = [p for p in self.rig.gh()["prs"] if p["number"] == 2]
        self.assertTrue(second["isDraft"], "an agent's ready PR on the item's branch stays ready")

    def test_a_dropped_commit_kept_on_a_ref_is_not_lost_by_the_next_drop(self):
        """drop_own_trees keeps a kept tree's unpushed commits at refs/worker/dropped/<tree>,
        and says so; the next run that drops a tree of the same name (item-<N> again) moves
        that ref with `update-ref`, so the commits it kept before reach no ref at all."""
        n, branch = self.item_with_pr(self.NOTE)
        self.rig.configure()
        w = self.rig.worker(self.ledger)
        source = w.root / "lib" / ".source"

        def commit_in(tree, name):
            (tree / name).write_text(f"{name}\n")
            git("add", name, cwd=tree)
            git("commit", "-q", "-m", name, cwd=tree)
            return git("rev-parse", "HEAD", cwd=tree).strip()

        kept = worker.make_workspace(w.root, w.wc.repos["lib"], n)  # an earlier run's tree
        first = commit_in(kept.path, "FIRST.txt")
        self.rig.agent_flags = ["--no-pr", "--exit", "1"]  # handed back, its tree kept
        self.run_it()
        trees = sorted(p for p in (w.root / "lib").iterdir() if p.name.startswith(f"item-{n}"))
        tree = next(p for p in trees if p.is_dir() and (p / ".git").exists())
        commit_in(tree, "SECOND.txt")
        time.sleep(1.1)  # a branch stamp of its own
        again = self.rig.worker(self.ledger)
        again.attempts.forget(again.cfg.ledger, n)  # `worker.py forget`: dispatched again
        again.run_once()
        holding = git("for-each-ref", "--contains", first, cwd=source).strip()
        self.assertTrue(holding, f"{first}, kept on a ref by the first drop, is on no ref now")


if __name__ == "__main__":
    unittest.main()
