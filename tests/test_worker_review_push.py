"""review-once (Michael with Pax, 2026-11-06): a reviewer loop's worker pushes the reviewer's
`review/pr-<n>` branches, never forced; the reviewer agent never pushes."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import worker  # noqa: E402

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "r",
    "GIT_AUTHOR_EMAIL": "reviewer@tamariz.invalid",
    "GIT_COMMITTER_NAME": "r",
    "GIT_COMMITTER_EMAIL": "reviewer@tamariz.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(cwd, *argv):
    p = subprocess.run(["git", *argv], cwd=cwd, env=ENV, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


class PushReviewBranches(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.origin = Path(d.name) / "origin.git"
        self.work = Path(d.name) / "work"
        git(d.name, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(d.name, "clone", "-q", str(self.origin), str(self.work))
        (self.work / "a.py").write_text("x = 1\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "base")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        self._env = dict(os.environ)
        os.environ.update(ENV)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._env)))

    def commit_test(self, branch, name="test_x.py"):
        git(self.work, "switch", "-q", "-c", branch)
        (self.work / name).write_text("assert False\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "review: a failing test")
        git(self.work, "switch", "-q", "--detach", "main")

    def on_origin(self, branch):
        argv = ["git", "--git-dir", str(self.origin), "rev-parse", "--verify", "-q", branch]
        return subprocess.run(argv, capture_output=True, text=True).stdout.strip()

    def test_a_review_branch_is_pushed(self):
        self.commit_test("review/pr-7")
        lines = worker.push_review_branches(self.work)
        self.assertEqual(1, len(lines))
        self.assertRegex(lines[0], r"^- review branch review/pr-7 at [0-9a-f]{12}: pushed$")
        self.assertTrue(self.on_origin("refs/heads/review/pr-7"))

    def test_no_review_branch_says_nothing(self):
        self.assertEqual([], worker.push_review_branches(self.work))

    def test_another_name_under_review_is_not_pushed(self):
        self.commit_test("review/main")
        lines = worker.push_review_branches(self.work)
        self.assertEqual(["- review branch review/main: not pushed (only review/pr-<n> is)"], lines)
        self.assertFalse(self.on_origin("refs/heads/review/main"))

    def test_a_push_that_isnt_a_fast_forward_is_reported_not_forced(self):
        self.commit_test("review/pr-7")
        worker.push_review_branches(self.work)
        before = self.on_origin("refs/heads/review/pr-7")
        git(self.work, "branch", "-q", "-f", "review/pr-7", "main")  # rewritten history
        (self.work / "b.py").write_text("y = 2\n")
        git(self.work, "switch", "-q", "review/pr-7")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "another")
        git(self.work, "switch", "-q", "--detach", "main")
        lines = worker.push_review_branches(self.work)
        self.assertIn(": NOT pushed: ", lines[0])
        self.assertEqual(before, self.on_origin("refs/heads/review/pr-7"))

    def test_a_branch_another_item_left_is_neither_pushed_nor_named(self):
        self.commit_test("review/pr-71")  # mago#618's review, left in the shared clone
        before, _ = worker.review_refs(self.work)
        self.assertEqual([], worker.push_review_branches(self.work, before))
        self.assertFalse(self.on_origin("refs/heads/review/pr-71"))

    def test_a_branch_the_agent_made_is_pushed(self):
        before, _ = worker.review_refs(self.work)
        self.commit_test("review/pr-59")
        lines = worker.push_review_branches(self.work, before)
        self.assertRegex(lines[0], r"^- review branch review/pr-59 at [0-9a-f]{12}: pushed$")

    def test_a_branch_the_agent_moved_is_pushed(self):
        self.commit_test("review/pr-7")
        worker.push_review_branches(self.work)
        before, _ = worker.review_refs(self.work)
        git(self.work, "switch", "-q", "review/pr-7")
        (self.work / "test_y.py").write_text("assert False\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "round 2: another failing test")
        git(self.work, "switch", "-q", "--detach", "main")
        lines = worker.push_review_branches(self.work, before)
        self.assertRegex(lines[0], r": pushed$")
        tip = git(self.work, "rev-parse", "review/pr-7")
        self.assertEqual(tip, self.on_origin("refs/heads/review/pr-7"))

    def test_a_branch_another_running_item_makes_is_neither_pushed_nor_named(self):
        # max_per_repo > 1: two review items run at once in worktrees of one clone, whose
        # branches are shared. Item 618 (PR 71) makes review/pr-71 while item 624 (PR 59) runs.
        other = self.work.parent / "item-618"
        git(self.work, "worktree", "add", "-q", "--detach", str(other), "main")
        before, _ = worker.review_refs(self.work)  # item 624 starts
        git(other, "switch", "-q", "-c", "review/pr-71")
        (other / "test_z.py").write_text("assert False\n")
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "PR 71's review")
        lines = worker.push_review_branches(self.work, before)  # item 624 hands back
        self.assertEqual([], lines)

    def test_a_listing_that_failed_at_the_start_does_not_push_every_branch(self):
        self.commit_test("review/pr-71")  # mago#618's review, left in the shared clone
        real = worker.git
        failed = []

        def flaky(*argv, cwd=None):
            if argv[0] == "for-each-ref" and not failed:
                failed.append(argv)
                return subprocess.CompletedProcess(argv, 128, "", "fatal: bad object\n")
            return real(*argv, cwd=cwd)

        self.addCleanup(setattr, worker, "git", real)
        worker.git = flaky
        before, _ = worker.review_refs(self.work)  # the start's listing fails
        worker.git = real
        worker.push_review_branches(self.work, before)
        self.assertFalse(self.on_origin("refs/heads/review/pr-71"))

    def test_a_reviewer_loop_pushes_and_a_coder_loop_does_not(self):
        src = (ROOT / "tools" / "worker.py").read_text()
        self.assertIn('review_before = review_refs(ws.path)[0] if "review" in self.wc.labels', src)
        self.assertIn("[] if review_before is None else push_review_branches(", src)
        self.assertIn("push_review_branches(ws.path, review_before, reviewed)", src)

    def test_a_branch_with_a_commit_above_the_reviewed_sha_is_pushed_at_that_commit(self):
        reviewed = git(self.work, "rev-parse", "main")
        git(self.work, "switch", "-q", "-c", "review/pr-414")
        (self.work / "test_flags.py").write_text("assert False\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "review: a failing test")
        tip = git(self.work, "rev-parse", "HEAD")
        git(self.work, "switch", "-q", "--detach", "main")
        lines = worker.push_review_branches(self.work, {}, reviewed)
        self.assertEqual([f"- review branch review/pr-414 at {tip[:12]}: pushed"], lines)
        self.assertEqual(tip, self.on_origin("refs/heads/review/pr-414"))

    def test_a_branch_at_the_reviewed_sha_is_not_pushed_and_says_why(self):
        reviewed = git(self.work, "rev-parse", "main")
        git(self.work, "branch", "review/pr-414", reviewed)  # the PR head; no review commit
        lines = worker.push_review_branches(self.work, {}, reviewed)
        self.assertEqual(1, len(lines))
        self.assertIn(f"review branch has no commits beyond {reviewed[:12]}", lines[0])
        self.assertNotIn(": pushed", lines[0])
        self.assertFalse(self.on_origin("refs/heads/review/pr-414"))


# The reviewer agent the loop runs below: it does what a review brief says (fetch the PR's head,
# detach to it, `git switch -c review/pr-<n>`), and commits nothing: it found no defect.
REVIEW_WITHOUT_A_COMMIT = """\
import subprocess, sys
for argv in (["fetch", "-q", "origin", "pr-7"], ["checkout", "-q", "--detach", "FETCH_HEAD"],
             ["switch", "-q", "-c", "review/pr-7"]):
    subprocess.run(["git", *argv], check=True)
with open(sys.argv[1], "w") as f:
    f.write("https://github.com/acme/lib/pull/7#pullrequestreview-1\\nREVIEW: clean\\n")
"""


class TheReviewerLoopPushesOnlyAReview(unittest.TestCase):
    """carducci#1705, through the loop: the worktree starts at origin/main, and the agent detaches
    to the PR head it reviews. A review/pr-<n> cut there with no commit of the agent's is the PR
    head, not a review: it must not be pushed, and the hand-back must not say `pushed`."""

    def setUp(self):
        import contextlib
        import io
        import json

        from worker_support import FakeLedger, Rig
        from worker_support import git as rgit

        self.json, self.rgit = json, rgit
        self.ledger = FakeLedger()
        self.rig = Rig(self)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        seed = self.rig.tmp / "seed"  # the PR's head, one commit above main: pull/7/head
        rgit("switch", "-q", "-c", "pr-7", cwd=seed)
        (seed / "feature.py").write_text("y = 2\n")
        rgit("add", "feature.py", cwd=seed)
        rgit("commit", "-q", "-m", "the PR", cwd=seed)
        rgit("push", "-q", str(self.rig.origin), "pr-7", cwd=seed)
        self.head = rgit("rev-parse", "HEAD", cwd=seed).strip()

    def test_a_review_branch_at_the_pr_head_is_not_pushed(self):
        agent = self.rig.tmp / "reviewer.py"
        agent.write_text(REVIEW_WITHOUT_A_COMMIT)
        path = self.rig.configure(labels='["worker:w1", "review"]')
        text = path.read_text()
        start = text.index("command = ", text.index("[agent]"))
        end = text.index("\n", start)
        command = self.json.dumps([sys.executable, str(agent), "{report_file}", "{prompt_file}"])
        path.write_text(text[:start] + f"command = {command}" + text[end:])
        n = self.ledger.file("Review PR 7", ["worker:w1", "review", "repo:lib"])
        self.rig.worker(self.ledger).run_once()
        said = "\n".join(c["text"] for c in self.ledger.human_comments(n))
        self.assertIn(f"review branch review/pr-7 at {self.head[:12]}", said)
        self.assertNotIn(f"review/pr-7 at {self.head[:12]}: pushed", said)
        self.assertNotIn("review/pr-7", self.rig.branches())


if __name__ == "__main__":
    unittest.main()
