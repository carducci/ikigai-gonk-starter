"""The worker's stories (tools/worker.py, worker/README.md "Stories"): one whole OpenSpec change
applied by one agent session. Hermetic: the in-memory ledger, a real git origin with a change in
it, the stub gh, the fake agent (`--tick`, `--hang`), a fake `openspec` on PATH and a fake build."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from support import gonk
from worker_support import FakeLedger, Rig, worker

CHANGE = "add-widget"


def story_labels(*changes: str) -> list[str]:
    return ["worker:w1", "repo:lib", "story", *(f"change:{c}" for c in changes)]


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


if __name__ == "__main__":
    unittest.main()
