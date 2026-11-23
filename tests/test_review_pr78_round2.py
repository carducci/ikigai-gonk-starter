"""Review of PR 78 (stories in the worker), round 2: each test fails at 7b7bda900d2d for the
defect its docstring names, and passes once that defect is fixed."""

from __future__ import annotations

import contextlib
import io
import unittest
from types import SimpleNamespace

from test_worker_story import BRANCH, CHANGE, StoryRig, story_labels
from worker_support import git, worker


class TheDispatchPinsTheChange(unittest.TestCase):
    def test_a_change_label_swapped_after_the_dispatch_routes_nothing(self):
        """dispatch_problem checks only that the newest router dispatch names the loop's labels
        and the `repo:` label, and story_change reads the item's labels as they are now: anyone
        who can write a label swaps `change:add-widget` for another change after the dispatch,
        and the worker applies that change on its story branch (README: "these labels, which
        the dispatch pins")."""
        s = StoryRig(self)
        n = s.story()  # dispatched naming worker:w1, repo:lib, story, change:add-widget
        item = s.ledger.items[n]
        item["labels"] = [w for w in item["labels"] if not w.startswith("change:")]
        item["labels"].append("change:other-widget")  # no dispatch names it
        with contextlib.redirect_stdout(io.StringIO()):
            s.run("--no-pr")
        prompt = s.rig.record / f"prompt-{n}.md"
        self.assertFalse(
            prompt.exists() and "`other-widget`" in prompt.read_text(),
            "the worker applied a change no router dispatched",
        )


class KeptWorkOfAnEarlierRunIsNotDestroyed(unittest.TestCase):
    def test_a_kept_tree_on_a_worker_branch_keeps_its_commits_when_the_item_becomes_a_story(self):
        """drop_own_trees pushes a kept tree's HEAD only when its branch is `story/...`; a tree
        an earlier plain run of the same item kept (`worker/item-N-...`) is removed with
        `worktree remove --force` and its branch deleted with `branch -D`, so its unpushed
        commits end on no ref (spec: removed "after a push of their HEAD that is never
        forced")."""
        s = StoryRig(self)
        n = s.ledger.file("Build the widget", ["worker:w1", "repo:lib"], body="Apply it.")
        with contextlib.redirect_stdout(io.StringIO()):
            s.run("--no-pr")  # no evidence: the worktree is kept
        tree = s.tree(n)
        self.assertTrue(tree.exists())
        (tree / "later.txt").write_text("work the plain run left unpushed\n")
        git("add", "later.txt", cwd=tree)
        git("commit", "-q", "-m", "Unpushed work", cwd=tree)
        mine = git("rev-parse", "HEAD", cwd=tree).strip()
        # The router makes it a story and dispatches it again.
        s.ledger.items[n]["labels"] = story_labels(CHANGE)
        s.ledger.dispatch(n)
        s.worker.attempts.forget("acme", n)
        with contextlib.redirect_stdout(io.StringIO()):
            s.run("--no-pr")
        source = s.rig.home / "work" / "lib" / ".source"
        holders = worker.git("for-each-ref", "--contains", mine, cwd=source).stdout
        on_origin = worker.git("for-each-ref", "--contains", mine, cwd=s.rig.origin).stdout
        self.assertTrue(
            holders.strip() or on_origin.strip(),
            "the earlier run's unpushed commit is on no ref here or on origin",
        )


class EveryUiPathIsSeen(unittest.TestCase):
    def test_a_ui_path_with_a_non_ascii_name_needs_a_screenshot(self):
        """story_checks matches `ui_globs` against `git diff --name-only`, which quotes a path
        with a non-ASCII byte (core.quotePath: `"web/caf\\303\\251.html"`), so no glob matches
        it and a UI change with no screenshot passes the screenshots check. (The same quoting
        hides a PNG named so from `git ls-tree`.)"""
        s = StoryRig(self)
        table = worker.load_story({"ui_globs": ["web/*"]}, "test")
        for name in ("plain.html", "café.html"):
            with self.subTest(name):
                tree = s.rig.tmp / f"clone-{len(name)}"
                git("clone", "-q", str(s.rig.origin), str(tree))
                git("checkout", "-q", "-b", BRANCH, cwd=tree)
                (tree / "web").mkdir()
                (tree / "web" / name).write_text("<p>widget</p>\n")
                git("add", "web", cwd=tree)
                git("commit", "-q", "-m", "A UI page", cwd=tree)
                ws = SimpleNamespace(path=tree, branch=BRANCH)
                checks = {c.name: c for c in worker.story_checks(ws, CHANGE, "main", table)}
                shots = checks["screenshots"]
                self.assertEqual(shots.result, "FAIL", shots.line)


if __name__ == "__main__":
    unittest.main()
