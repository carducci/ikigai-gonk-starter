"""Review of PR 78 (stories in the worker), round 1: each test fails at e7165b734f74 for the
defect its docstring names, and passes once that defect is fixed."""

from __future__ import annotations

import contextlib
import io
import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from test_worker_story import BRANCH, CHANGE, StoryRig
from worker_support import git, worker


def hook(origin: Path, body: str) -> None:
    """A pre-receive hook in the scratch origin."""
    path = origin / "hooks" / "pre-receive"
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)


class RefusedCheckpointIsNotReady(unittest.TestCase):
    def test_a_story_whose_last_push_was_refused_is_not_marked_ready(self):
        """finish_story ignores last_checkpoint's result and never compares the PR's head with
        the HEAD it checked: when origin refuses the push, the checks pass on commits the pull
        request does not hold, and that pull request is marked ready and handed back as done."""
        s = StoryRig(self)
        # The story's branch exists on origin with nothing ticked, and its draft is open.
        git("push", "-q", str(s.rig.origin), f"main:refs/heads/{BRANCH}", cwd=s.seed)
        pushed = s.origin_head(BRANCH)
        url = "https://github.com/acme/lib/pull/1"
        draft = {
            "number": 1, "url": url, "state": "OPEN", "headRefName": BRANCH,
            "headRefOid": pushed, "baseRefName": "main", "isDraft": True,
            "isCrossRepository": False,
        }  # fmt: skip
        s.rig.gh_state.write_text(json.dumps({"slug": "acme/lib", "prs": [draft]}))
        hook(s.rig.origin, 'echo "refused: protected" >&2; exit 1')
        n = s.story()
        outcome = s.run("--no-pr", "--tick", "3", story=s.build("pass"))
        self.assertEqual(s.origin_head(BRANCH), pushed, "origin never got the ticks")
        self.assertNotEqual(outcome.code, worker.HANDED_BACK, outcome.summary)
        self.assertTrue(s.rig.gh()["prs"][0]["isDraft"], "a PR without the checked work is ready")
        said = "\n".join(c["text"] for c in s.ledger.human_comments(n))
        self.assertNotIn("Evidence:", said)


class KeptWorkIsNotDestroyed(unittest.TestCase):
    def test_a_refused_push_of_a_kept_tree_keeps_its_commits(self):
        """drop_own_trees logs a refused push and then runs `worktree remove --force` and
        `branch -D` anyway, so the kept tree's unpushed commits are left on no ref at all."""
        s = StoryRig(self)
        n = s.story()
        s.run("--no-pr", "--tick", "1")  # no build configured: handed back, tree kept
        tree = s.tree(n)
        self.assertTrue(tree.exists())
        (tree / "later.txt").write_text("work after the last checkpoint\n")
        git("add", "later.txt", cwd=tree)
        git("commit", "-q", "-m", "Unpushed work", cwd=tree)
        mine = git("rev-parse", "HEAD", cwd=tree).strip()
        # Someone else moves origin's story branch, so the never-forced push is refused.
        (s.seed / "theirs.txt").write_text("theirs\n")
        git("add", "theirs.txt", cwd=s.seed)
        git("commit", "-q", "-m", "Theirs", cwd=s.seed)
        git("push", "-q", "-f", str(s.rig.origin), f"HEAD:refs/heads/{BRANCH}", cwd=s.seed)
        s.worker.attempts.forget("acme", n)
        with contextlib.redirect_stdout(io.StringIO()):
            s.run("--no-pr")
        source = s.rig.home / "work" / "lib" / ".source"
        holders = worker.git("for-each-ref", "--contains", mine, cwd=source).stdout
        on_origin = worker.git("for-each-ref", "--contains", mine, cwd=s.rig.origin).stdout
        self.assertTrue(
            holders.strip() or on_origin.strip(),
            "the kept tree's unpushed commit is on no ref here or on origin",
        )


class ChecksReadWhatIsCommitted(unittest.TestCase):
    def test_a_tick_left_uncommitted_does_not_pass_the_tasks_check(self):
        """story_checks reads tasks.md (and the screenshots, and runs the build) in the working
        tree, so a tick the agent never committed passes, though the pull request still has the
        box open."""
        s = StoryRig(self)
        tree = s.rig.tmp / "clone"
        git("clone", "-q", str(s.rig.origin), str(tree))
        tasks = tree / "openspec" / "changes" / CHANGE / "tasks.md"
        tasks.write_text(tasks.read_text().replace("- [ ]", "- [x]"))  # not committed
        ws = SimpleNamespace(path=tree, branch=BRANCH)
        checks = worker.story_checks(ws, CHANGE, "main", worker.load_story({}, "test"))
        tasks_check = {c.name: c for c in checks}["tasks"]
        self.assertFalse(
            all(c.passed for c in checks if c.name != "build"),
            f"every check but build passed on an uncommitted tick: {tasks_check.line}",
        )


class ACheckpointCannotHoldTheBudget(unittest.TestCase):
    def test_a_hanging_push_does_not_keep_the_agent_past_its_budget(self):
        """StoryWatch.checkpoint runs `git push` (no timeout) inside Worker.watch, so a push
        that hangs blocks the overrun, lost-claim and shutdown checks until it returns."""
        s = StoryRig(self)
        hook(s.rig.origin, "sleep 30")
        s.story()
        stopped: list[float] = []
        real = worker.stop_process

        def stop(proc, grace):
            stopped.append(time.monotonic())
            return real(proc, grace)

        start = time.monotonic()
        with mock.patch.object(worker, "stop_process", side_effect=stop):
            s.run("--no-pr", "--tick", "1", "--hang", story='check = "1s"', budget='"3s"')
        self.assertTrue(stopped, "the agent was never stopped")
        self.assertLess(stopped[0] - start, 15, "the agent ran on while a push hung")


class ReviewsKeepTheirMachineSlots(unittest.TestCase):
    def test_a_review_still_waits_for_a_coder_running_here(self):
        """RepoLock's new `kind` gives reviews slots of their own (`<repo>.review.lock`), so a
        review no longer waits for a coder's item running on this machine: an item without the
        story label does not run as before."""
        s = StoryRig(self)
        s.rig.configure(labels='["worker:w1", "review"]')
        state = s.rig.worker(s.ledger).wc.state_dir
        held = worker.RepoLock(state, "lib")
        self.assertTrue(held.acquire())
        self.addCleanup(held.release)
        n = s.ledger.file("Review PR 9", ["worker:w1", "repo:lib", "review"])
        s.rig.configure(labels='["worker:w1", "review"]')
        w = s.rig.worker(s.ledger)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            outcome = w.run_once()
        self.assertEqual(outcome.code, worker.NOTHING, outcome.summary)
        self.assertIsNone(s.ledger.items[n]["claim"])
        self.assertIn("has 1 item(s) running here", out.getvalue())


class TheChangeIdIsWhole(unittest.TestCase):
    def test_a_change_id_with_a_trailing_newline_is_refused(self):
        """CHANGE_ID ends in `$`, which re.match lets match before a trailing newline, so
        `change:add-widget\\n` passes as a change id."""
        item = {"labels": ["worker:w1", "repo:lib", "story", "change:add-widget\n"]}
        self.assertIsNotNone(worker.story_problem(item))
        self.assertFalse(worker.is_story(item))


class TheCostLineSurvivesItsLog(unittest.TestCase):
    def test_a_huge_integer_cost_does_not_raise(self):
        """log_usage calls float() on an int total_cost_usd, which raises OverflowError (not
        caught) for an integer past a float's range: the agent's own output crashes the
        hand-back."""
        text = '{"type": "result", "num_turns": 1, "total_cost_usd": 1' + "0" * 400 + "}"
        usage = worker.log_usage(text)
        self.assertIsNotNone(usage)


if __name__ == "__main__":
    unittest.main()
