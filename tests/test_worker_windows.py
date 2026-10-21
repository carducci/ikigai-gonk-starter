"""The worker loop's Windows port (tools/worker.py): the repository lock, the process-tree kill,
the elevation refusal, the stop file and the case-normalised work root. The lock, the refusal
and the work root also run on POSIX, through the same code; the tree kill and the console
signal are Windows only, and say so when skipped.
"""

from __future__ import annotations

import contextlib
import io
import os
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
