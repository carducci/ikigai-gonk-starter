"""The sweep of left-over worktrees and review branches before an item (carducci#1858, carducci#1829)."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from worker_support import worker


def git(*args, cwd):
    return worker.git(*args, cwd=cwd)


class Sweep(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = Path(d.name)
        self.origin = root / "origin.git"
        seed = root / "seed"
        git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=root)
        git("init", "-q", "-b", "main", str(seed), cwd=root)
        for k, v in (("user.name", "t"), ("user.email", "t@t")):
            git("config", k, v, cwd=seed)
        (seed / "a.txt").write_text("a\n")
        git("add", "a.txt", cwd=seed)
        git("commit", "-q", "-m", "a", cwd=seed)
        git("push", "-q", str(self.origin), "main", cwd=seed)
        self.home = root / "work" / "lib"
        self.home.mkdir(parents=True)
        self.source = self.home / ".source"
        git("clone", "-q", "--no-checkout", str(self.origin), str(self.source), cwd=root)
        for k, v in (("user.name", "t"), ("user.email", "t@t")):
            git("config", k, v, cwd=self.source)

    def tree(self, n, age_hours, commit=False, review=None):
        path = self.home / f"item-{n}"
        git("worktree", "add", "-q", "-b", f"worker/item-{n}-x", str(path), "origin/main", cwd=self.source)
        if commit:
            (path / "w.txt").write_text("unpushed\n")
            git("add", "w.txt", cwd=path)
            git("commit", "-q", "-m", "unpushed", cwd=path)
        if review:
            git("branch", review, "HEAD", cwd=path)
        t = time.time() - age_hours * 3600
        os.utime(path, (t, t))
        return path

    def test_an_old_unclaimed_tree_goes_and_its_unpushed_commit_is_kept(self):
        old = self.tree(5, 48, commit=True)
        tip = git("rev-parse", "HEAD", cwd=old).stdout.strip()
        lines = worker.sweep_stale_trees(self.home, 9, held=set())
        self.assertFalse(old.exists())
        self.assertTrue(git("for-each-ref", "--contains", tip, "refs/worker/dropped/", cwd=self.source).stdout.strip())
        self.assertTrue(any("item 5" in ln for ln in lines))

    def test_a_held_tree_a_young_tree_and_the_current_item_stay(self):
        held, young, mine = self.tree(6, 48), self.tree(7, 1), self.tree(9, 48)
        worker.sweep_stale_trees(self.home, 9, held={6})
        self.assertTrue(held.exists() and young.exists() and mine.exists())

    def test_a_stale_local_review_branch_goes_and_a_checked_out_one_stays(self):
        live = self.tree(8, 1)
        git("checkout", "-q", "-b", "review/pr-8", cwd=live)
        git("branch", "review/pr-539", "origin/main", cwd=self.source)  # a dead run's, on no tree
        worker.sweep_stale_trees(self.home, 9, held={8})
        heads = git("for-each-ref", "--format=%(refname:short)", "refs/heads/review/", cwd=self.source).stdout.split()
        self.assertEqual(["review/pr-8"], heads)

    def test_no_clone_yet_sweeps_nothing(self):
        self.assertEqual([], worker.sweep_stale_trees(self.home.parent / "none", 1, held=set()))


if __name__ == "__main__":
    unittest.main()
