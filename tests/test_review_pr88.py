"""Review of PR 88 at 411b7f4 (carducci#1884): the sweep of left-over worktrees and review
branches. Each test fails at 411b7f4 for the defect its docstring names."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from worker_support import worker


def git(*args, cwd):
    return worker.git(*args, cwd=cwd)


class SweepReview(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = Path(d.name)
        origin = root / "origin.git"
        seed = root / "seed"
        git("init", "-q", "--bare", "-b", "main", str(origin), cwd=root)
        git("init", "-q", "-b", "main", str(seed), cwd=root)
        for k, v in (("user.name", "t"), ("user.email", "t@t")):
            git("config", k, v, cwd=seed)
        (seed / "a.txt").write_text("a\n")
        git("add", "a.txt", cwd=seed)
        git("commit", "-q", "-m", "a", cwd=seed)
        git("push", "-q", str(origin), "main", cwd=seed)
        self.root = root / "work"
        self.home = self.root / "lib"
        self.home.mkdir(parents=True)
        self.source = self.home / ".source"
        git("clone", "-q", "--no-checkout", str(origin), str(self.source), cwd=root)
        for k, v in (("user.name", "t"), ("user.email", "t@t")):
            git("config", k, v, cwd=self.source)

    def tree(self, name, age_hours):
        path = self.home / name
        branch = f"worker/{name}-x"
        git("worktree", "add", "-q", "-b", branch, str(path), "origin/main", cwd=self.source)
        t = time.time() - age_hours * 3600
        os.utime(path, (t, t))
        return path

    def unpushed(self, message):
        """A commit on top of origin/main that origin never got."""
        tree = git("rev-parse", "origin/main^{tree}", cwd=self.source).stdout.strip()
        made = git("commit-tree", tree, "-p", "origin/main", "-m", message, cwd=self.source)
        return made.stdout.strip()

    def test_a_young_tree_of_an_item_that_also_has_an_old_tree_stays(self):
        """The sweep picks item NUMBERS with any stale tree, then drop_own_trees removes every
        tree of that number, so a tree changed an hour ago goes too, against "haven't changed
        for a day"."""
        self.tree("item-5", 48)
        young = self.tree("item-5.2", 1)
        worker.sweep_stale_trees(self.home, 9, held=set())
        self.assertTrue(young.exists(), "a tree changed an hour ago was swept")

    def test_a_second_sweep_of_a_review_branch_keeps_the_first_ones_tip(self):
        """The branch sweep keeps an unpushed tip with an unconditional update-ref on
        refs/worker/dropped/<branch>, so a later dead run's review/pr-8 moves that ref and the
        first run's commit reaches no ref ("nothing is lost")."""
        first = self.unpushed("round 1's failing test")
        git("branch", "review/pr-8", first, cwd=self.source)
        worker.sweep_stale_trees(self.home, 9, held=set())
        second = self.unpushed("round 2's failing test")
        git("branch", "review/pr-8", second, cwd=self.source)
        worker.sweep_stale_trees(self.home, 9, held=set())
        kept = git("for-each-ref", "--contains", first, cwd=self.source).stdout.strip()
        self.assertTrue(kept, f"round 1's commit {first[:12]} is on no ref after the sweeps")

    def test_a_ledger_answer_with_no_items_list_sweeps_nothing(self):
        """Worker.sweep promises "when the claims can't be read, nothing is swept", but
        Ledger.items reads an answer with no `items` key as an empty list: no claims, so every
        old tree goes, claimed or not."""
        claimed = self.tree("item-6", 48)
        out = '{"error": "the items resource is unavailable"}'
        answer = SimpleNamespace(ok=True, out=out, code=0, text=lambda: "")
        ikigai = SimpleNamespace(run=lambda command, stdin=None: answer)
        cfg = SimpleNamespace(resource=lambda name: f"urn:ledger:{name}")
        ledger = worker.Ledger(cfg, ikigai)
        fake = SimpleNamespace(ledger=ledger, root=self.root)
        worker.Worker.sweep(fake, SimpleNamespace(name="lib"), 9)
        self.assertTrue(claimed.exists(), "a tree was swept on an answer that named no claims")


if __name__ == "__main__":
    unittest.main()
