"""The worker loop's Windows port (tools/worker.py): the repository lock, the process-tree kill,
the elevation refusal, the stop file and the case-normalised work root. The lock, the refusal
and the work root also run on POSIX, through the same code; the tree kill and the console
signal are Windows only, and say so when skipped.
"""

from __future__ import annotations

import unittest

from support import scratch_repo
from worker_support import worker


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
