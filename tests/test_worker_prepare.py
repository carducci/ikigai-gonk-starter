"""A repository's prepare steps (tools/worker.py), hermetic: run in the worktree, in order,
before the agent; a step that fails or times out hands the item back without starting it."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
import time
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
            f'routers = {json.dumps([DISPATCHER])}\nlabels = ["worker:w1"]\n'
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

    def test_a_zero_timeout_is_refused_naming_the_repository(self):
        for bad in ['prepare_timeout = "0s"', 'prepare_timeout = "PT0S"', 'prepare_timeout = "0m"']:
            with self.assertRaises(gonk.ConfigError, msg=bad) as ctx:
                self.load(bad)
            self.assertIn("[repos.lib]", str(ctx.exception), bad)

    def test_an_integer_timeout_names_its_repository(self):
        with self.assertRaises(gonk.ConfigError) as ctx:
            self.load("prepare_timeout = 900")
        self.assertIn("[repos.lib]", str(ctx.exception))

    def test_an_argv_element_that_cannot_run_is_refused_naming_the_repository(self):
        for bad in [
            'prepare = [["a\\u0000b"]]',
            'prepare = [[" "]]',
            'prepare = [["npm", "a\\u0000"]]',
            'prepare = [[""]]',
        ]:
            with self.assertRaises(gonk.ConfigError, msg=bad) as ctx:
                self.load(bad)
            self.assertIn("[repos.lib]", str(ctx.exception), bad)


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

    def assertHandedBackWithoutEvidence(self, n: int):
        self.assertIsNone(self.ledger.items[n].get("claim"))
        comments = self.ledger.items[n]["comments"]
        self.assertEqual([c for c in comments if c["text"].startswith("Evidence:")], [])
        self.assertTrue(any("hands" in c["text"] for c in comments), comments)

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
        self.assertIn(f"prepare step `{sys.executable} -c ", outcome.summary)
        self.assertIn("exited 3", outcome.summary)
        self.assertIn("line 29", outcome.summary)
        self.assertIn("line 10", outcome.summary)
        self.assertNotIn("line 9\n", outcome.summary)
        self.assertEqual((self.marks / "order").read_text().count("\n"), 1)
        self.assertFalse(self.agent_started(n))
        self.assertHandedBackWithoutEvidence(n)

    def test_a_step_that_times_out_does_the_same(self):
        n = self.ledger.file("Hangs", ["worker:w1", "repo:lib"])
        slow = "import time;print('starting',flush=True);time.sleep(30)"
        outcome = self.run_once([py(slow)], timeout=1)
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn("timed out after 0m01s", outcome.summary)
        self.assertIn("starting", outcome.summary)
        self.assertIn("prepare step `" + sys.executable, outcome.summary)
        self.assertFalse(self.agent_started(n))
        self.assertHandedBackWithoutEvidence(n)

    def test_a_step_that_does_not_exist_does_the_same(self):
        n = self.ledger.file("Missing", ["worker:w1", "repo:lib"])
        outcome = self.run_once([["no-such-program-892"]])
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn("prepare step `no-such-program-892` did not start", outcome.summary)
        self.assertFalse(self.agent_started(n))
        self.assertHandedBackWithoutEvidence(n)

    def grandchild(self, mark: Path) -> list[str]:
        """A step that leaves a grandchild behind: it writes `mark` after 3 s, if still alive."""
        child = f"import time;time.sleep(3);open({str(mark)!r},'w').write('x')"
        return py(
            "import subprocess,sys,time;"
            f"subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(30)"
        )

    def test_a_timed_out_step_takes_its_children_with_it(self):
        n = self.ledger.file("Orphans", ["worker:w1", "repo:lib"])
        mark = self.marks / "grandchild"
        outcome = self.run_once([self.grandchild(mark)], timeout=1)
        self.assertIn("timed out", outcome.summary)
        time.sleep(3.5)
        self.assertFalse(mark.exists(), "a grandchild of the step outlived its timeout")
        self.assertHandedBackWithoutEvidence(n)

    def test_a_shutdown_stops_a_step_and_hands_back_without_evidence(self):
        n = self.ledger.file("Stopped", ["worker:w1", "repo:lib"])
        self.rig.configure()
        w = self.rig.worker(self.ledger)
        w.wc.repos["lib"].prepare = [py("import time;time.sleep(5)")] * 2
        timer = threading.Timer(0.5, w.shutdown.set)
        timer.start()
        self.addCleanup(timer.cancel)
        began = time.monotonic()
        outcome = w.run_once()
        self.assertLess(time.monotonic() - began, 4)
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn("prepare step", outcome.summary)
        self.assertIn("worker was stopped", outcome.summary)
        self.assertFalse(self.agent_started(n))
        self.assertHandedBackWithoutEvidence(n)

    def test_a_lost_claim_stops_a_step_and_posts_without_evidence_or_release(self):
        n = self.ledger.file("Lost", ["worker:w1", "repo:lib"])
        self.rig.configure()
        w = self.rig.worker(self.ledger)
        w.wc.repos["lib"].prepare = [py("import time;time.sleep(20)")]
        timer = threading.Timer(0.5, lambda: setattr(self.ledger, "refuse_renewals", True))
        timer.start()
        self.addCleanup(timer.cancel)
        began = time.monotonic()
        outcome = w.run_once()
        self.assertLess(time.monotonic() - began, 10)
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn("prepare step", outcome.summary)
        self.assertIn("claim was lost", outcome.summary)
        self.assertFalse(self.agent_started(n))
        comments = self.ledger.items[n]["comments"]
        self.assertEqual([c for c in comments if c["text"].startswith("Evidence:")], [])
        self.assertTrue(any("prepare step" in c["text"] for c in comments), comments)

    def test_a_configuration_without_prepare_runs_as_before(self):
        n = self.ledger.file("Plain", ["worker:w1", "repo:lib"])
        outcome = self.run_once()
        self.assertEqual(outcome.code, worker.HANDED_BACK, outcome.summary)
        self.assertTrue(self.agent_started(n))


if __name__ == "__main__":
    unittest.main()
