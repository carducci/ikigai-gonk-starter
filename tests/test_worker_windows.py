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
from unittest import mock

from support import scratch_repo
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
