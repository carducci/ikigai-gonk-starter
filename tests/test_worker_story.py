"""The worker's stories (tools/worker.py, worker/README.md "Stories"): one whole OpenSpec change
applied by one agent session. Hermetic: the in-memory ledger, a real git origin with a change in
it, the stub gh, the fake agent (`--tick`, `--hang`), a fake `openspec` on PATH and a fake build."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from support import gonk
from worker_support import FakeLedger, Rig, git, worker

CHANGE = "add-widget"


def story_labels(*changes: str) -> list[str]:
    return ["worker:w1", "repo:lib", "story", *(f"change:{c}" for c in changes)]


class StoryRig:
    """A rig whose origin's main has the change `add-widget`, with three open tasks."""

    def __init__(self, test: unittest.TestCase, tasks: int = 3) -> None:
        self.test = test
        self.rig = Rig(test)
        self.ledger = FakeLedger()
        self.seed = self.rig.tmp / "seed"
        change = self.seed / "openspec" / "changes" / CHANGE
        change.mkdir(parents=True)
        (change / "proposal.md").write_text("# Add a widget\n")
        (change / "tasks.md").write_text(
            "".join(f"- [ ] {i}. Task {i}\n" for i in range(1, tasks + 1))
        )
        git("add", "openspec", cwd=self.seed)
        git("commit", "-q", "-m", "Propose add-widget", cwd=self.seed)
        git("push", "-q", str(self.rig.origin), "main", cwd=self.seed)

    def story(self, body: str = "Apply add-widget.") -> int:
        return self.ledger.file("Build the widget", story_labels(CHANGE), body=body)

    def run(self, *flags: str, story: str | None = None, **configure):
        self.rig.agent_flags = ["--change", CHANGE, *flags]
        self.rig.configure(story=story, **configure)
        self.worker = self.rig.worker(self.ledger)
        return self.worker.run_once()

    def origin_head(self, branch: str) -> str:
        return git("rev-parse", branch, cwd=self.rig.origin).strip()

    def tree(self, number: int) -> Path:
        return self.rig.home / "work" / "lib" / f"item-{number}"


class TellingAStory(unittest.TestCase):
    def test_one_change_label_makes_a_story(self):
        item = {"labels": story_labels(CHANGE)}
        self.assertTrue(worker.is_story(item))
        self.assertEqual(worker.story_change(item), CHANGE)
        self.assertIsNone(worker.story_problem(item))

    def test_an_item_without_the_story_label_is_no_story_and_no_problem(self):
        item = {"labels": ["worker:w1", "repo:lib", f"change:{CHANGE}"]}
        self.assertFalse(worker.is_story(item))
        self.assertIsNone(worker.story_problem(item))

    def test_no_change_two_changes_or_a_bad_id_is_a_problem(self):
        for changes, said in (
            ((), "none"),
            (("a", "b"), "change:a, change:b"),
            (("Add_Widget",), "'Add_Widget'"),
            (("-lead",), "'-lead'"),
            (("x" * 65,), "is not a change id"),
        ):
            item = {"labels": story_labels(*changes)}
            self.assertFalse(worker.is_story(item), changes)
            self.assertIn(said, worker.story_problem(item), changes)


class TheStoryTable(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(self)

    def load(self, story: str | None):
        cfg = gonk.load(self.rig.checkout)
        return worker.load_worker(cfg, self.rig.configure(story=story)).story

    def test_without_one_it_has_the_defaults(self):
        story = self.load(None)
        self.assertEqual((story["stall"], story["check"]), (1800, 60))
        self.assertIsNone(story["build"])
        self.assertEqual(story["ui_globs"], [])
        self.assertEqual(story["evidence"], "openspec/changes/{change}/evidence/screenshots")

    def test_its_settings_are_read(self):
        story = self.load(
            'stall = "5m"\ncheck = "10s"\nbuild = "just gates"\nui_globs = ["web/**"]\n'
            'evidence = "docs/shots/{change}"'
        )
        self.assertEqual((story["stall"], story["check"]), (300, 10))
        self.assertEqual(story["build"], ["just", "gates"])
        self.assertEqual(story["ui_globs"], ["web/**"])
        self.assertEqual(story["evidence"], "docs/shots/{change}")

    def test_what_it_refuses(self):
        for bad in (
            'colour = "red"',
            "build = []",
            "build = [1]",
            'ui_globs = "web/**"',
            'evidence = "/abs"',
            'evidence = "../out"',
            'stall = "soon"',
            'check = "0s"',
        ):
            with self.subTest(bad), self.assertRaises(gonk.ConfigError):
                self.load(bad)


class Selection(unittest.TestCase):
    def setUp(self):
        self.rig, self.ledger = Rig(self), FakeLedger()

    def test_a_story_naming_no_change_or_two_is_skipped_saying_why(self):
        self.ledger.file("No change", story_labels())
        self.ledger.file("Two changes", story_labels("a", "b"))
        self.rig.configure()
        w = self.rig.worker(self.ledger)
        take, skip, err = w.candidates()
        self.assertIsNone(err)
        self.assertEqual(take, [])
        self.assertEqual([d for d, _ in skip], ["acme#1", "acme#2"])
        self.assertIn("exactly one OpenSpec change", skip[1][1])
        self.assertEqual(w.run_once().code, worker.NOTHING)

    def test_a_small_items_loop_without_story_never_sees_one(self):
        self.ledger.file("A story", story_labels(CHANGE))
        plain = self.ledger.file("A small item", ["worker:w1", "repo:lib"])
        self.rig.configure(without='["story"]')
        w = self.rig.worker(self.ledger)
        take, skip, _ = w.candidates()
        self.assertEqual([i["number"] for i, _ in take], [plain])
        self.assertEqual(skip, [])
        self.assertEqual(w.why_not(self.ledger.items[plain], datetime.now(UTC), {}), None)


class TheBranch(unittest.TestCase):
    def setUp(self):
        self.s = StoryRig(self)

    def test_a_new_story_starts_from_main_on_its_own_branch(self):
        n = self.s.story()
        main = self.s.origin_head("main")
        self.s.run()
        self.assertEqual((self.s.rig.record / f"head-{n}").read_text(), main)
        self.assertIn(f"story/{CHANGE}", self.s.rig.branches())

    def test_a_story_resumes_from_its_branch_on_origin(self):
        seed = self.s.seed
        tasks = seed / "openspec" / "changes" / CHANGE / "tasks.md"
        tasks.write_text(tasks.read_text().replace("- [ ]", "- [x]", 1))
        git("commit", "-q", "-am", "Tick task 1", cwd=seed)
        git("push", "-q", str(self.s.rig.origin), f"HEAD:refs/heads/story/{CHANGE}", cwd=seed)
        resumed = self.s.origin_head(f"story/{CHANGE}")
        n = self.s.story()
        self.s.run()
        self.assertEqual((self.s.rig.record / f"head-{n}").read_text(), resumed)

    def test_its_own_kept_worktree_is_pushed_then_removed_and_the_next_run_resumes(self):
        n = self.s.story()
        self.s.run("--no-pr", "--tick", "1")  # no evidence: the worktree is kept
        ticked = git("rev-parse", "HEAD", cwd=self.s.tree(n)).strip()
        self.s.worker.attempts.forget("acme", n)
        self.s.run("--no-pr")
        self.assertEqual((self.s.rig.record / f"head-{n}").read_text(), ticked)
        self.assertEqual(self.s.origin_head(f"story/{CHANGE}"), ticked)
        self.assertFalse((self.s.rig.home / "work" / "lib" / f"item-{n}.2").exists())


if __name__ == "__main__":
    unittest.main()
