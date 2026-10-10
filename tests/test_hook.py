"""Unit tests for the optional Claude Code hook: a fake runner, no gonk."""

from __future__ import annotations

import json
import unittest

from support import FakeIkigai, load_hook, ok, scratch_repo

hook = load_hook()


def item(holder, expires="2999-01-01T00:00:00Z"):
    claim = {"holder": holder, "expires": expires} if holder else None
    return ok(json.dumps({"item": {"display": "acme#12", "status": "open", "claim": claim}}))


class RequireClaim(unittest.TestCase):
    def setUp(self):
        self.repo = scratch_repo(self)
        (self.repo / ".gonk" / "gonk.toml").write_text('ledger = "acme"\n')
        (self.repo / ".gonk" / "local.toml").write_text(
            f'transport = "socket"\nsocket = "{self.repo / "g.sock"}"\nholder = "agent-1"\n'
        )

    def edit(self, path, tool="Edit"):
        return {"tool_name": tool, "tool_input": {"file_path": str(path)}, "cwd": str(self.repo)}

    def claim(self):
        state = self.repo / ".gonk" / "state"
        state.mkdir(exist_ok=True)
        (state / "claim.toml").write_text('ledger = "acme"\nitem = 12\nholder = "agent-1"\n')

    def test_an_edit_with_no_claim_is_refused(self):
        code, message = hook.decide(self.edit(self.repo / "artifacts" / "x.py"), FakeIkigai())
        self.assertEqual(code, 2)
        self.assertIn("holds no claim", message)

    def test_an_edit_under_a_live_claim_passes(self):
        self.claim()
        fake = FakeIkigai([("item:12", item("agent-1"))])
        self.assertEqual(hook.decide(self.edit(self.repo / "README.md"), fake), (0, ""))

    def test_an_edit_after_a_takeover_is_refused(self):
        self.claim()
        fake = FakeIkigai([("item:12", item("someone-else"))])
        code, message = hook.decide(self.edit(self.repo / "README.md", "Write"), fake)
        self.assertEqual(code, 2)
        self.assertIn("README.md", message)

    def test_a_relative_path_is_read_from_the_sessions_directory(self):
        code, _ = hook.decide(self.edit("artifacts/x.py"), FakeIkigai())
        self.assertEqual(code, 2)

    def test_the_protocols_own_files_are_always_writable(self):
        for rel in [".gonk/state/claim.toml", ".gonk/local.toml"]:
            self.assertEqual(hook.decide(self.edit(self.repo / rel), FakeIkigai()), (0, ""))

    def test_other_tools_and_other_trees_are_not_its_business(self):
        bash = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        self.assertEqual(hook.decide(bash, FakeIkigai()), (0, ""))
        outside = self.edit(self.repo.parent / "elsewhere" / "x.py")
        self.assertEqual(hook.decide(outside, FakeIkigai()), (0, ""))

    def test_an_unwired_repository_is_refused_with_the_reason(self):
        (self.repo / ".gonk" / "local.toml").unlink()
        code, message = hook.decide(self.edit(self.repo / "README.md"), FakeIkigai())
        self.assertEqual(code, 2)
        self.assertIn("not wired to gonk", message)


if __name__ == "__main__":
    unittest.main()
