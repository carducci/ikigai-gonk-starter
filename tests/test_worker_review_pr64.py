"""Review of PR #64 (carducci#1578): a loop skips what its sibling handed back.

Each case fails at a6730c54577d because of a defect the review reproduced, and passes at the base.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from worker_support import FakeLedger, Rig, worker


class SiblingHandBack(unittest.TestCase):
    def setUp(self):
        self.ledger = FakeLedger()
        self.rig = Rig(self)
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def test_a_hand_back_written_by_a_non_worker_does_not_unroute_a_dispatch(self):
        # Routing is read only from comments by a router (dispatch_problem); any ledger writer
        # can add a comment. One by a principal that is neither a router nor a worker, naming
        # a made-up loop, must not stop every loop from taking what a router dispatched.
        self.rig.configure()
        n = self.ledger.file("Dispatched", ["worker:w1", "repo:lib"])
        note = f"gonk worker `w1-2` handed acme#{n} back without evidence: exited 1."
        self.ledger.add_comment(n, note, author="mallory")
        take, skip, _ = self.rig.worker(self.ledger).candidates()
        self.assertEqual([i["number"] for i, _ in take], [n], dict(skip))

    def test_forget_allows_an_item_again_when_a_sibling_also_handed_it_back(self):
        # Both loops tried the item for one dispatch (the carducci#1562 bug). The skip line and
        # AGENTS.md say `worker.py forget N` allows it again; after forget the loop still skips.
        self.rig.agent_flags = ["--no-pr", "--exit", "1"]
        self.rig.configure()
        n = self.ledger.file("Gives up", ["worker:w1", "repo:lib"])
        self.assertEqual(self.rig.worker(self.ledger).run_once().code, worker.NOT_HANDED_BACK)
        note = f"gonk worker `w1-2` handed acme#{n} back without evidence: exited 1."
        self.ledger.add_comment(n, note)
        w = self.rig.worker(self.ledger)
        self.assertTrue(w.attempts.forget("acme", n))
        take, skip, _ = w.candidates()
        self.assertEqual([i["number"] for i, _ in take], [n], dict(skip))


if __name__ == "__main__":
    unittest.main()
