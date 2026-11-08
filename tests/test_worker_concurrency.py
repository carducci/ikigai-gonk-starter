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
import json
import threading
import time
import unittest

from support import gonk
from worker_support import DISPATCHER, FakeLedger, Rig, worker


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

    def test_by_default_one_claim_fences_the_repository(self):
        busy = self.ledger.file("Someone is on lib", ["repo:lib"])
        self.ledger.force_claim(busy, "chris")
        lib = self.ledger.file("Also lib", ["worker:w1", "repo:lib"])
        take, skip, _ = self.candidates()
        self.assertEqual([i["number"] for i, _ in take], [])
        self.assertIn(
            (
                f"acme#{lib}",
                f"repo:lib is busy: acme#{busy} is claimed by `chris` (one agent per repository)",
            ),
            skip,
        )

    def test_an_idle_holders_claim_fences_nothing(self):  # a router's hold (carducci#1451)
        self.ledger.force_claim(self.ledger.file("Held", ["repo:lib"]), "dax-router")
        lib = self.ledger.file("Also lib", ["worker:w1", "repo:lib"])
        take = self.candidates(idle_holders='["dax-router"]')[0]
        self.assertEqual([i["number"] for i, _ in take], [lib])

    def test_up_to_max_per_repo_claims_share_a_repository(self):
        first = self.ledger.file("Someone is on lib", ["repo:lib"])
        self.ledger.force_claim(first, "chris")
        lib = self.ledger.file("Also lib", ["worker:w1", "repo:lib"])
        take, _, _ = self.candidates(max_per_repo="2")
        self.assertEqual([i["number"] for i, _ in take], [lib])

        second = self.ledger.file("Someone else on lib", ["repo:lib"])
        self.ledger.force_claim(second, "dana")
        take, skip, _ = self.candidates(max_per_repo="2")
        self.assertEqual([i["number"] for i, _ in take], [])
        [(_, why)] = [s for s in skip if s[0] == f"acme#{lib}"]
        self.assertEqual(
            why,
            f"repo:lib is busy: acme#{first} is claimed by `chris`, acme#{second} is claimed by "
            "`dana` (2 agents per repository)",
        )

    def test_a_review_claim_does_not_fence_a_coder(self):
        review = self.ledger.file("Review lib", ["repo:lib", "review"])
        self.ledger.force_claim(review, "reviewer")
        lib = self.ledger.file("Code lib", ["worker:w1", "repo:lib"])
        take, _, _ = self.candidates()
        self.assertEqual([i["number"] for i, _ in take], [lib])

    def test_a_coder_claim_does_not_fence_a_reviewer_but_a_review_claim_does(self):
        code = self.ledger.file("Code lib", ["repo:lib"])
        self.ledger.force_claim(code, "coder")
        lib = self.ledger.file("Review lib", ["worker:w1", "review", "repo:lib"])
        labels = '["worker:w1", "review"]'
        take, _, _ = self.candidates(labels=labels)
        self.assertEqual([i["number"] for i, _ in take], [lib])

        other = self.ledger.file("Another review of lib", ["repo:lib", "review"])
        self.ledger.force_claim(other, "reviewer-2")
        take, _, _ = self.candidates(labels=labels)
        self.assertEqual([i["number"] for i, _ in take], [])

    def test_this_machine_runs_up_to_max_per_repo_items_of_a_repository(self):
        self.rig.configure(max_per_repo="2")
        w = self.rig.worker(self.ledger)
        one = worker.RepoLock(w.wc.state_dir, "lib", slots=2)
        two = worker.RepoLock(w.wc.state_dir, "lib", slots=2)
        three = worker.RepoLock(w.wc.state_dir, "lib", slots=2)
        self.assertTrue(one.acquire())
        self.addCleanup(one.release)
        self.assertTrue(two.acquire())
        self.addCleanup(two.release)
        self.assertFalse(three.acquire())
        one.release()
        self.assertTrue(three.acquire())
        self.addCleanup(three.release)

    def test_a_one_slot_lock_is_the_old_lock_file(self):
        # A loop on the old code and one on the new, sharing a checkout in a deploy, still fence.
        self.rig.configure()
        w = self.rig.worker(self.ledger)
        new = worker.RepoLock(w.wc.state_dir, "lib", slots=1)
        self.assertTrue(new.acquire())
        self.addCleanup(new.release)
        self.assertEqual(new.path, w.wc.state_dir / "locks" / "lib.lock")

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


class MaxPerRepoConfiguration(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(self)
        self.path = self.rig.checkout / ".gonk" / "worker.toml"

    def load(self, extra: str):
        self.path.write_text(
            f"routers = {json.dumps([DISPATCHER])}\n"
            + 'labels = ["worker:w1"]\n'
            + extra
            + '\n[agent]\npreset = "codex"\n[repos.lib]\nremote = "https://github.com/acme/lib.git"\n'
        )
        return worker.load_worker(gonk.load(self.rig.checkout))

    def test_the_default_is_one(self):
        self.assertEqual(self.load("").max_per_repo, 1)

    def test_a_number_from_one(self):
        self.assertEqual(self.load("max_per_repo = 3").max_per_repo, 3)

    def test_zero_a_negative_and_a_word_are_refused(self):
        for bad in ("0", "-1", '"two"', "true"):
            with self.subTest(bad=bad), self.assertRaises(gonk.ConfigError) as e:
                self.load(f"max_per_repo = {bad}")
            self.assertIn("max_per_repo", str(e.exception))

    def test_idle_holders_is_a_list_of_names(self):
        self.assertEqual(self.load('idle_holders = ["dax-router"]').idle_holders, ("dax-router",))
        with self.assertRaises(gonk.ConfigError):
            self.load('idle_holders = "dax-router"')

    def test_an_idle_holder_that_is_not_a_holder_name_is_refused(self):
        # No claim carries such a name, so it never matches: the hold it was meant for still
        # fences the repository and the loop deadlocks as before, with nothing said.
        for bad in ('"dax-router "', '" dax-router"', '"dax router"', '"any"'):
            with self.subTest(bad=bad):
                with self.assertRaises(gonk.ConfigError) as e:
                    self.load(f"idle_holders = [{bad}]")
                self.assertIn("idle_holders", str(e.exception))


if __name__ == "__main__":
    unittest.main()
