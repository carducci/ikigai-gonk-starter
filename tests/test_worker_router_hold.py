"""A router's hold is not an agent in the repository (2026-11-08).

Dax's router claims each task it holds in flight as `dax-router` (ikigraph flow-on-kata-flight D10),
so the doctor can tell a dead router from abandoned work. Those holds are on tasks waiting for a
review or a merge, with no agent working them, but `max_per_repo` counted them: the carducci coder
loop skipped ikigraph for twenty minutes with "repo:ikigraph is busy: carducci#1431 is claimed by
`dax-router`". A hold still keeps its own item from being taken (it is claimed).
"""

from __future__ import annotations

import contextlib
import io
import unittest

from worker_support import FakeLedger, Rig


class RouterHold(unittest.TestCase):
    def setUp(self):
        self.ledger = FakeLedger()
        self.rig = Rig(self)
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def candidates(self):
        self.rig.configure()
        return self.rig.worker(self.ledger).candidates()

    @unittest.expectedFailure
    def test_a_router_hold_does_not_fence_the_repository(self):
        held = self.ledger.file("In flight, waiting for its review", ["repo:lib"])
        self.ledger.force_claim(held, "dax-router")
        lib = self.ledger.file("Code lib", ["worker:w1", "repo:lib"])
        take, _, _ = self.candidates()
        self.assertEqual([i["number"] for i, _ in take], [lib])

    def test_the_held_item_itself_is_still_not_taken(self):
        held = self.ledger.file("In flight", ["worker:w1", "repo:lib"])
        self.ledger.force_claim(held, "dax-router")
        take, _, _ = self.candidates()
        self.assertEqual([i["number"] for i, _ in take], [])

    def test_an_agents_claim_still_fences_it(self):
        busy = self.ledger.file("Someone is on lib", ["repo:lib"])
        self.ledger.force_claim(busy, "chris")
        self.ledger.file("Code lib", ["worker:w1", "repo:lib"])
        take, _, _ = self.candidates()
        self.assertEqual([i["number"] for i, _ in take], [])


if __name__ == "__main__":
    unittest.main()
