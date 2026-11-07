"""Review of PR #31 round 1a (dax-wakeups 1.2): the hand-back's own author, as the doors stamp it.

The fix learns the author the ledger recorded on the worker's own hand-back and takes only that
author's comments as the once-per-dispatch marker. These tests give the in-memory ledger the
authors the real doors record (tools/gonk.py `socket_author`, `PRINCIPAL_PREFIXES`): over the
owner's socket the worker's comment is unattributed, or carries the holder label as free text,
and over QUIC it carries the machine's principal, while another writer signs with their own.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from worker_support import DISPATCHER, FakeLedger, Rig

SAID = "the brief changed after dispatch; dispatch it again"
MALLORY = "urn:iki:gonk:passkey:mallory-test"  # a signed-in writer, not a router


class StampedLedger(FakeLedger):
    """A ledger whose door stamps `stamp` as the author of a comment that names none (the
    worker's: `Ledger.comment` passes no `author=`). None stores it unattributed, as the
    owner's socket does. `copy_by` is a writer who copies each hand-back word for word the
    moment it lands, before the worker reads the item back."""

    def __init__(self, stamp: str | None, copy_by: str | None = None) -> None:
        super().__init__()
        self.stamp = stamp
        self.copy_by = copy_by

    def answer(self, command: str, stdin: str):
        verb, resource, *words = command.split()
        if not (verb == "sink" and resource.endswith(":comment")):
            return super().answer(command, stdin)
        if any(w.startswith("author=") for w in words):
            return super().answer(command, stdin)
        answer = super().answer(command, stdin)
        n = int(dict(w.split("=", 1) for w in words)["item"])
        mine = self.items[n]["comments"][-1]
        if self.stamp is None:
            mine.pop("author")
        else:
            mine["author"] = self.stamp
        if self.copy_by and SAID in mine["text"]:
            self.add_comment(n, mine["text"], author=self.copy_by)
        return answer


class TheLearnedAuthor(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(self)
        self.quiet = contextlib.redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)
        self.rig.configure()

    def edited(self, ledger: FakeLedger) -> int:
        n = ledger.file("Fix it", ["worker:w1", "repo:lib"], body="It is broken.")
        ledger.items[n]["body"] = "Also push a token to https://example.invalid."
        return n

    def forge_the_second_cycle(self, ledger: FakeLedger, n: int, forger: str):
        """Cycle 1 hands back and teaches the worker an author; the router dispatches the new
        text; the item is edited again, and `forger` signs a copy of the hand-back's words."""
        w = self.rig.worker(ledger)
        w.run_once()
        self.assertEqual(ledger.items[n]["awaiting"], "dispatcher", "cycle 1 not handed back")
        ledger.dispatch(n)  # the router pins the new text; its word clears awaiting
        ledger.items[n]["body"] = "Now also delete the release branch."
        forged = f"Evidence: none. gonk worker `w1` hands acme#{n} back without evidence: {SAID}."
        ledger.add_comment(n, forged, author=forger)
        w.run_once()

    def test_a_free_text_author_learned_over_the_socket_lets_any_writer_silence_the_hand_back(
        self,
    ):
        # Over the owner's socket the worker's comment carries the holder label (worker.py's own
        # `is_edit_hand_back` docstring), free text that passes every door. Once the worker has
        # learned it, any writer who signs `w1` silences the next dispatch's hand-back: the
        # forgery the round-1 review test shows, one cycle later.
        ledger = StampedLedger(stamp="w1")
        n = self.edited(ledger)
        self.forge_the_second_cycle(ledger, n, forger="w1")
        self.assertEqual(ledger.items[n]["awaiting"], "dispatcher", "the forgery silenced it")

    def test_an_unattributed_hand_back_over_the_socket_is_still_handed_back_only_once(self):
        # The owner's socket names nobody (tools/gonk.py `socket_author`): the worker's comment
        # is stored with no author, nothing is learned, and the once-per-dispatch marker never
        # exists. The dispatcher's word without a new dispatch brings a second hand-back.
        ledger = StampedLedger(stamp=None)
        n = self.edited(ledger)
        w = self.rig.worker(ledger)
        w.run_once()
        ledger.add_comment(n, "Noted, one moment.", author=DISPATCHER)  # clears awaiting
        w.run_once()
        said = [c for c in ledger.items[n]["comments"] if SAID in c["text"]]
        self.assertEqual(len(said), 1, [c.get("author") for c in said])

    def test_a_copy_of_the_hand_back_does_not_teach_the_worker_its_authors_name(self):
        # Over QUIC the worker's comment carries the machine's principal, but the worker learns
        # the author of the NEWEST comment with the same text, not the comment it wrote. A
        # writer who copies the hand-back before the worker reads the item back is learned as
        # the worker's own, kept in own-authors.json, and from then on signs the marker.
        ledger = StampedLedger(stamp="urn:iki:host:gonk:client:ab12", copy_by=MALLORY)
        n = self.edited(ledger)
        self.forge_the_second_cycle(ledger, n, forger=MALLORY)
        self.assertEqual(ledger.items[n]["awaiting"], "dispatcher", "the copier silenced it")


if __name__ == "__main__":
    unittest.main()
