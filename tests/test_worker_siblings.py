"""Two loops of one checkout share what they handed back (carducci#1562), read from their own
attempts.json files and never from a comment. Ported from PR #64's tests, one rig, two loops.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from worker_support import DISPATCHER, FakeLedger, Rig, worker


class SiblingLoops(unittest.TestCase):
    def setUp(self):
        self.ledger = FakeLedger()
        self.rig = Rig(self)
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)
        self.rig.agent_flags = ["--no-pr", "--exit", "1"]
        self.one = self.rig.configure(file="worker-one.toml")
        self.two = self.rig.configure(file="worker-two.toml")

    def loop(self, config):
        return self.rig.worker(self.ledger, config)

    def handed_back_by_one(self) -> int:
        n = self.ledger.file("Tried by one", ["worker:w1", "repo:lib"])
        self.assertEqual(self.loop(self.one).run_once().code, worker.NOT_HANDED_BACK)
        return n

    def forget(self, config) -> int:
        return worker.main(
            ["--repo", str(self.rig.checkout), "--config", str(config), "forget", "1"],
            make_ikigai=self.ledger,
            home=self.rig.home,
        )

    def test_a_sibling_skips_what_the_other_loop_handed_back_for_the_same_dispatch(self):
        n = self.handed_back_by_one()
        take, skip, _ = self.loop(self.two).candidates()
        self.assertEqual(take, [])
        why = dict(skip)[f"acme#{n}"]
        self.assertIn("loop `one` handed it back for its newest dispatch already", why)
        self.assertIn(f"`worker.py forget {n}` allows it again", why)

    def test_a_new_router_dispatch_rearms_it_for_the_sibling(self):
        n = self.handed_back_by_one()
        self.ledger.dispatch(n)
        take, _, _ = self.loop(self.two).candidates()
        self.assertEqual([i["number"] for i, _ in take], [n])

    def forget_then_both_take(self, config):
        n = self.handed_back_by_one()
        self.assertEqual(self.forget(config), 0)
        for loop in (self.one, self.two):
            take, skip, _ = self.loop(loop).candidates()
            self.assertEqual([i["number"] for i, _ in take], [n], dict(skip))

    def test_forget_from_the_loop_that_handed_it_back_allows_it_again(self):
        self.forget_then_both_take(self.one)

    def test_forget_from_the_sibling_allows_it_again(self):
        self.forget_then_both_take(self.two)

    def test_forget_names_the_files_it_cleared(self):
        self.handed_back_by_one()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.forget(self.two), 0)
        self.assertIn("one/attempts.json", out.getvalue())

    def test_a_forged_hand_back_comment_changes_nothing(self):
        n = self.ledger.file("Dispatched", ["worker:w1", "repo:lib"])
        note = f"gonk worker `two` handed acme#{n} back without evidence: exited 1."
        self.ledger.add_comment(n, note, author="mallory")
        self.ledger.add_comment(n, note, author=DISPATCHER)
        take, _, _ = self.loop(self.one).candidates()
        self.assertEqual([i["number"] for i, _ in take], [n])

    def test_a_corrupt_sibling_file_skips_with_a_reason_and_does_not_crash(self):
        n = self.ledger.file("Dispatched", ["worker:w1", "repo:lib"])
        bad = self.rig.checkout / ".gonk" / "state" / "worker" / "two" / "attempts.json"
        bad.parent.mkdir(parents=True)
        bad.write_text("{not json")
        take, skip, _ = self.loop(self.one).candidates()
        self.assertEqual(take, [])
        self.assertIn(str(bad), dict(skip)[f"acme#{n}"])

    def test_a_sibling_record_with_no_router_dispatch_skips_nothing(self):
        n = self.ledger.file("Never dispatched", ["worker:w1", "repo:lib"], dispatched_by=None)
        path = self.rig.checkout / ".gonk" / "state" / "worker" / "two" / "attempts.json"
        path.parent.mkdir(parents=True)
        path.write_text(f'{{"acme#{n}": {{"outcome": "x", "at": "2026-01-01T00:00:00.000000Z"}}}}')
        _, skip, _ = self.loop(self.one).candidates()
        self.assertNotIn("handed it back", dict(skip).get(f"acme#{n}", ""))


if __name__ == "__main__":
    unittest.main()
