"""The starter's own shape: what a new repository made from it must carry."""

from __future__ import annotations

import os
import unittest

from support import ROOT


class Shape(unittest.TestCase):
    def test_claude_md_is_a_link_to_agents_md(self):
        link = ROOT / "CLAUDE.md"
        self.assertTrue(link.is_symlink(), "CLAUDE.md must be a symlink, so there is one file")
        self.assertEqual(os.readlink(link), "AGENTS.md")

    def test_every_reserved_directory_has_a_readme(self):
        for rel in [
            ".gonk",
            ".gonk/queries",
            ".gonk/scripts",
            "openspec",
            "openspec/specs",
            "openspec/changes",
            "artifacts",
            "hooks/claude",
        ]:
            self.assertTrue((ROOT / rel / "README.md").is_file(), rel)

    def test_no_ledger_is_named_in_the_template(self):
        # A fresh repository must say which ledger is its own; init reports it missing.
        text = (ROOT / ".gonk" / "gonk.toml").read_text()
        self.assertFalse(any(line.startswith("ledger") for line in text.splitlines()), text)

    def test_the_core_rules_name_no_agent_specific_tool(self):
        core = (ROOT / "AGENTS.md").read_text().split("## Optional: a hook for Claude Code")[0]
        for word in ["PreToolUse", "Bash tool", "TodoWrite", "MultiEdit", "Edit tool"]:
            self.assertNotIn(word, core)


if __name__ == "__main__":
    unittest.main()
