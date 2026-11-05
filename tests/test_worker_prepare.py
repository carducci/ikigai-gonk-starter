"""A repository's prepare steps (tools/worker.py), hermetic: run in the worktree, in order,
before the agent; a step that fails or times out hands the item back without starting it."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

from support import gonk
from worker_support import DISPATCHER, FakeLedger, Rig, worker

REPO = '\n[repos.lib]\nremote = "https://github.com/acme/lib.git"\n'


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


class PrepareConfiguration(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(self)

    def load(self, extra: str):
        path = self.rig.checkout / ".gonk" / "worker.toml"
        path.write_text(
            f"routers = {json.dumps([DISPATCHER])}\nlabels = [\"worker:w1\"]\n"
            f'[agent]\npreset = "codex"\n{REPO}{extra}\n'
        )
        return worker.load_worker(gonk.load(self.rig.checkout))

    def test_no_prepare_is_no_steps_and_fifteen_minutes(self):
        repo = self.load("").repos["lib"]
        self.assertEqual((repo.prepare, repo.prepare_timeout), ([], 900))

    def test_steps_and_a_timeout_are_read(self):
        repo = self.load(
            'prepare = [["git", "submodule", "update", "--init"], ["npm", "ci"]]\n'
            'prepare_timeout = "2m"'
        ).repos["lib"]
        self.assertEqual(repo.prepare, [["git", "submodule", "update", "--init"], ["npm", "ci"]])
        self.assertEqual(repo.prepare_timeout, 120)

    def test_a_step_that_is_not_an_argv_list_is_refused(self):
        for bad in ['prepare = ["npm ci"]', 'prepare = "npm ci"', "prepare = [[]]"]:
            with self.assertRaises(gonk.ConfigError, msg=bad):
                self.load(bad)


class PrepareSteps(unittest.TestCase):
    def setUp(self):
        self.ledger = FakeLedger()
        self.rig = Rig(self)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.marks = self.rig.record.parent / "marks"
        self.marks.mkdir()

    def run_once(self, prepare=None, timeout=None):
        self.rig.configure()
        w = self.rig.worker(self.ledger)
        repo = w.wc.repos["lib"]
        if prepare is not None:
            repo.prepare = prepare
        if timeout is not None:
            repo.prepare_timeout = timeout
        return w.run_once()

    def mark(self, name: str) -> list[str]:
        code = (
            "import os,sys;"
            f"open({str(self.marks / 'order')!r},'a').write('{name} '+os.getcwd()+'\\n')"
        )
        return py(code)

    def agent_started(self, n: int) -> bool:
        return (self.rig.record / f"started-{n}").exists()

    def test_steps_run_in_order_in_the_worktree_before_the_agent(self):
        n = self.ledger.file("Prepared", ["worker:w1", "repo:lib"])
        outcome = self.run_once([self.mark("one"), self.mark("two")])
        self.assertEqual(outcome.code, worker.HANDED_BACK, outcome.summary)
        cwd = Path((self.rig.record / f"cwd-{n}").read_text()).resolve()
        lines = (self.marks / "order").read_text().splitlines()
        self.assertEqual([x.split(" ", 1)[0] for x in lines], ["one", "two"])
        for line in lines:
            self.assertEqual(Path(line.split(" ", 1)[1]).resolve(), cwd)
        self.assertTrue(self.agent_started(n))

    def test_a_failing_step_hands_back_with_its_name_and_output_and_no_agent(self):
        n = self.ledger.file("Fails", ["worker:w1", "repo:lib"])
        loud = "import sys;print('\\n'.join(f'line {i}' for i in range(30)));sys.exit(3)"
        outcome = self.run_once([self.mark("ok"), py(loud), self.mark("never")])
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn("prepare step", outcome.summary)
        self.assertIn("exited 3", outcome.summary)
        self.assertIn("line 29", outcome.summary)
        self.assertIn("line 10", outcome.summary)
        self.assertNotIn("line 9\n", outcome.summary)
        self.assertEqual((self.marks / "order").read_text().count("\n"), 1)
        self.assertFalse(self.agent_started(n))
        self.assertIsNone(self.ledger.items[n].get("claim"))
        self.assertEqual(
            [c for c in self.ledger.items[n]["comments"] if c["text"].startswith("Evidence:")], []
        )

    def test_a_step_that_times_out_does_the_same(self):
        n = self.ledger.file("Hangs", ["worker:w1", "repo:lib"])
        slow = "import time;print('starting',flush=True);time.sleep(30)"
        outcome = self.run_once([py(slow)], timeout=1)
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn("timed out after 0m01s", outcome.summary)
        self.assertIn("starting", outcome.summary)
        self.assertFalse(self.agent_started(n))

    def test_a_step_that_does_not_exist_does_the_same(self):
        n = self.ledger.file("Missing", ["worker:w1", "repo:lib"])
        outcome = self.run_once([["no-such-program-892"]])
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn("no-such-program-892", outcome.summary)
        self.assertFalse(self.agent_started(n))

    def test_a_configuration_without_prepare_runs_as_before(self):
        n = self.ledger.file("Plain", ["worker:w1", "repo:lib"])
        outcome = self.run_once()
        self.assertEqual(outcome.code, worker.HANDED_BACK, outcome.summary)
        self.assertTrue(self.agent_started(n))


if __name__ == "__main__":
    unittest.main()
