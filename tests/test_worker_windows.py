"""The worker loop's Windows port (tools/worker.py): the repository lock, the process-tree kill,
the elevation refusal, the stop file and the case-normalised work root. The lock, the refusal
and the work root also run on POSIX, through the same code; the tree kill and the console
signal are Windows only, and say so when skipped.
"""

from __future__ import annotations

import contextlib
import io
import os
import signal
import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from support import gonk, scratch_repo
from worker_support import FakeLedger, Rig, worker


class TheRepositoryLock(unittest.TestCase):
    def test_a_second_holder_of_one_repository_is_refused(self):
        state = scratch_repo(self) / "state"
        first, second = worker.RepoLock(state, "lib"), worker.RepoLock(state, "lib")
        self.assertTrue(first.acquire())
        self.addCleanup(first.release)
        self.assertFalse(second.acquire(), "two loops would share one worktree")
        self.assertIsNone(second.handle)
        first.release()
        self.assertTrue(second.acquire(), "released, the lock is free again")
        self.addCleanup(second.release)
        other = worker.RepoLock(state, "other")
        self.assertTrue(other.acquire(), "another repository has its own lock")
        self.addCleanup(other.release)


class TheElevationRefusal(unittest.TestCase):
    def test_an_elevated_worker_refuses_to_start(self):
        rig = Rig(self)
        rig.configure()
        err = io.StringIO()
        with mock.patch.object(worker, "elevated", lambda: True), contextlib.redirect_stderr(err):
            code = worker.main(["--repo", str(rig.checkout), "run", "--once"], FakeLedger())
        self.assertEqual(code, worker.CONFIG)
        self.assertIn("refusing to run", err.getvalue())
        self.assertIn("elevated" if os.name == "nt" else "as root", err.getvalue())

    @unittest.skipUnless(os.name == "nt", "the administrator token exists only on Windows")
    def test_the_real_token_check_answers_with_a_bool(self):
        self.assertIsInstance(worker.elevated(), bool)


class TheWorkRootIsCaseNormalised(unittest.TestCase):
    def setUp(self):
        self.home = scratch_repo(self) / "Agent"
        self.home.mkdir()

    def test_a_work_root_in_other_case_is_still_under_home(self):
        # Windows folds case in a path, POSIX does not: so POSIX is given the fold. Either way
        # the comparison must go through os.path.normcase, which the spy shows.
        fold = os.path.normcase if os.name == "nt" else str.lower
        shouted = str(self.home).swapcase() + os.sep + "WORK" + os.sep + "x"
        with mock.patch("os.path.normcase", mock.Mock(wraps=fold)) as spy:
            self.assertEqual(worker.work_root(shouted, self.home), Path(shouted).resolve())
            self.assertTrue(spy.called)
            with self.assertRaises(gonk.ConfigError):
                worker.work_root(str(self.home).swapcase(), self.home)

    @unittest.skipIf(os.name == "nt", "Windows folds case, so there is no other-case root outside")
    def test_without_the_fold_another_case_is_another_directory(self):
        with self.assertRaises(gonk.ConfigError):
            worker.work_root(str(self.home).swapcase() + "/work", self.home)


def alive(pid: int) -> bool:
    out = subprocess.run(
        ["tasklist", "/NH", "/FI", f"PID eq {pid}"], capture_output=True, text=True
    ).stdout
    return str(pid) in out


class TheLoop(unittest.TestCase):
    def setUp(self):
        self.ledger = FakeLedger()
        self.rig = Rig(self)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def test_the_stop_file_stops_an_idle_loop_within_a_poll(self):
        self.rig.configure(poll='"1s"')
        w = self.rig.worker(self.ledger)
        codes = []
        thread = threading.Thread(target=lambda: codes.append(w.loop()))
        thread.start()
        time.sleep(0.3)  # idle: nothing is ready, so it is waiting out the poll
        w.wc.stop_file.parent.mkdir(parents=True, exist_ok=True)
        w.wc.stop_file.write_text("")
        thread.join(timeout=3)  # one poll is 1 s
        self.assertFalse(thread.is_alive(), "the loop did not stop within a poll")
        self.assertEqual(codes, [0])

    @unittest.skipUnless(hasattr(signal, "SIGBREAK"), "Ctrl+Break is Windows only")
    def test_ctrl_break_stops_the_loop_as_sigterm_does(self):
        self.rig.configure()
        registered = {}
        with (
            mock.patch.object(worker.signal, "signal", lambda s, h: registered.update({s: h})),
            mock.patch.object(worker.Worker, "loop", lambda self: 0),
        ):
            code = worker.main(
                ["--repo", str(self.rig.checkout), "run"], self.ledger, self.rig.home
            )
        self.assertEqual(code, 0)
        self.assertIn(signal.SIGBREAK, registered)
        self.assertIs(registered[signal.SIGBREAK], registered[signal.SIGINT])

    @unittest.skipUnless(os.name == "nt", "the process-tree kill is the Windows path")
    def test_a_timed_out_agent_is_killed_with_its_child(self):
        for flags in (["--child"], ["--child", "--stubborn"]):  # polite, then deaf to the break
            with self.subTest(flags=flags):
                self.rig.agent_flags = ["--sleep", "60", *flags]
                n = self.ledger.file(f"Too big {flags}", ["worker:w1", "repo:lib"])
                self.rig.configure(budget='"3s"', grace='"2s"')
                started = time.monotonic()
                outcome = self.rig.worker(self.ledger).run_once()
                self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
                self.assertLess(time.monotonic() - started, 30)
                agent, child = map(int, (self.rig.record / f"child-{n}").read_text().split())
                self.assertFalse(alive(child), "the agent's child outlived the agent")
                self.assertFalse(alive(agent), "the agent is still running")
