"""More than one agent per repository, up to `max_per_repo` (Michael with Pax, 2026-11-06).

One agent per repository held the whole team to two or three agents in flight: every item of a
ledger is mostly in one repository, and the lock was held for the whole run. Each item already has a
worktree of its own, so only the shared clone (`<work root>/<repo>/.source`) needs one writer at a
time: the clone lock is held while a worktree is set up, prepared and removed, never while the
agent runs. `max_per_repo` (default 1, today's behaviour) caps how many items of one repository run
at once, on the ledger and on this machine. A review claim fences only reviewers, and a coder's
claim only coders: the reviewer loops have a checkout and a clone of their own.
"""

from __future__ import annotations

import contextlib
import io
import threading
import time
import unittest

from worker_support import FakeLedger, Rig, worker


class MaxPerRepo(unittest.TestCase):
    def setUp(self):
        self.ledger = FakeLedger()
        self.rig = Rig(self)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def candidates(self, **config):
        self.rig.configure(**config)
        return self.rig.worker(self.ledger).candidates()

    def test_the_clone_lock_is_free_while_the_agent_runs(self):
        self.rig.agent_flags = ["--sleep", "4"]
        self.ledger.file("Slow lib work", ["worker:w1", "repo:lib"])
        self.rig.configure()
        w = self.rig.worker(self.ledger)
        result = {}
        run = threading.Thread(target=lambda: result.setdefault("outcome", w.run_once()))
        run.start()
        self.addCleanup(run.join, 30)
        deadline = time.monotonic() + 20
        home = w.root / "lib"
        while time.monotonic() < deadline and not any(home.glob("item-*/.gonk/state")):
            time.sleep(0.1)
        time.sleep(1)  # past the worktree's setup: the agent is running now
        self.assertTrue(run.is_alive(), "the agent finished before the clone lock was checked")
        clone = worker.CloneLock(w.wc.state_dir, "lib")
        self.assertTrue(clone.acquire(timeout=0), "the clone lock is held while the agent runs")
        clone.release()
        run.join(30)
        self.assertEqual(result["outcome"].code, worker.HANDED_BACK, result["outcome"].summary)


if __name__ == "__main__":
    unittest.main()
