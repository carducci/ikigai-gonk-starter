"""Review of PR #67 (carducci#1583): `forget` and a sibling loop's corrupt attempts file."""

from __future__ import annotations

import contextlib
import io
import unittest

from worker_support import FakeLedger, Rig, worker


class ForgetBesideACorruptSibling(unittest.TestCase):
    def test_forget_clears_this_loops_record_when_a_sibling_file_is_corrupt(self):
        ledger = FakeLedger()
        rig = Rig(self)
        rig.configure("worker-one.toml")
        two = rig.configure("worker-two.toml")
        n = ledger.file("Gives up", ["worker:w1", "repo:lib"])
        loop = rig.worker(ledger, two)
        loop.attempts.record("acme", n, "handed back")
        sibling = loop.wc.state_dir / "one" / "attempts.json"
        sibling.parent.mkdir(parents=True, exist_ok=True)
        sibling.write_text("{not json", encoding="utf-8")
        argv = ["--repo", str(rig.checkout), "forget", str(n), "--config", str(two)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = worker.main(argv, make_ikigai=ledger)
        # This loop's own record must go, whatever a sibling's file holds: before the sweep,
        # `forget` read only this loop's file and cleared it.
        self.assertIsNone(loop.attempts.seen("acme", n), err.getvalue())
        self.assertEqual(code, 0, err.getvalue())


if __name__ == "__main__":
    unittest.main()
