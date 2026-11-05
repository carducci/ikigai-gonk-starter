"""One argv rule for every command list worker.py loads (tools/worker.py): the list is not
empty, its program is not blank, no element holds NUL; any other element runs as written."""

from __future__ import annotations

import json
import unittest

from support import gonk
from worker_support import DISPATCHER, Rig, worker

REPO = '\n[repos.lib]\nremote = "https://github.com/acme/lib.git"\n'


class ArgvRule(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(self)

    def load(self, top: str = "", agent: str = 'preset = "codex"', tail: str = ""):
        path = self.rig.checkout / ".gonk" / "worker.toml"
        path.write_text(
            f'routers = {json.dumps([DISPATCHER])}\nlabels = ["worker:w1"]\n{top}\n'
            f"[agent]\n{agent}\n{REPO}{tail}\n"
        )
        return worker.load_worker(gonk.load(self.rig.checkout))

    def refused(self, key: str, **kw):
        with self.assertRaises(gonk.ConfigError, msg=repr(kw)) as ctx:
            self.load(**kw)
        text = str(ctx.exception)
        self.assertIn("worker.toml", text)
        self.assertIn(key, text)

    def test_prepare_refuses_a_blank_program_or_a_nul_and_names_its_section(self):
        for bad in [
            '[[" "]]',
            '[["\\u00a0"]]',
            '[["\\u3000"]]',
            '[[""]]',
            '[["a\\u0000b"]]',
            '[["npm", "a\\u0000"]]',
            "[[]]",
        ]:
            self.refused("[repos.lib] prepare", tail=f"prepare = {bad}")

    def test_prepare_passes_a_blank_argument_as_written(self):
        repo = self.load(tail='prepare = [["npm", "\\t\\n", "", " ", "\\r"]]').repos["lib"]
        self.assertEqual(repo.prepare, [["npm", "\t\n", "", " ", "\r"]])

    def test_agent_command(self):
        for bad in [
            '["a\\u0000b", "{prompt}"]',
            '["", "{prompt}"]',
            '[" ", "{prompt}"]',
            '["codex", "{prompt}\\u0000"]',
            '" "',
        ]:
            self.refused("[agent] command", agent=f"command = {bad}")
        wc = self.load(agent='command = ["codex", "", " ", "{prompt}"]')
        self.assertEqual(wc.command, ["codex", "", " ", "{prompt}"])

    def test_gh_in_both_forms(self):
        for bad in ["[]", '" "', '""', '[""]', '["g\\u0000h"]', '[" "]', '["gh", "a\\u0000"]']:
            self.refused("gh", top=f"gh = {bad}")
        self.assertEqual(self.load(top='gh = ["gh", ""]').gh, ["gh", ""])
        self.assertEqual(self.load(top='gh = "gh --x"').gh, ["gh", "--x"])

    def test_usage_command(self):
        for bad in ['["a\\u0000b"]', '[""]', '[" "]', '["x", "a\\u0000"]', "[]"]:
            self.refused("[usage] command", tail=f"[usage]\ncommand = {bad}")
        wc = self.load(tail='[usage]\ncommand = ["usage", ""]')
        self.assertEqual(wc.usage["command"], ["usage", ""])

    def test_profile_obeys_the_argv_rule_after_substitution(self):
        cmd = 'command = ["hermes", "--profile", "{profile}", "-z", "{prompt}"]'
        for bad in ['"a\\u0000b"', "5", '"x\\u0000"']:
            self.refused("[agent] profile", agent=f"{cmd}\nprofile = {bad}")
        wc = self.load(agent=f"{cmd}\nprofile = \" \"")  # an argument runs as written
        self.assertEqual(wc.profile, " ")
        program = 'command = ["{profile}", "{prompt}"]'
        for bad in ['" "', '"\\u00a0"']:
            self.refused("[agent] profile", agent=f"{program}\nprofile = {bad}")
        self.assertEqual(self.load(agent=f'{program}\nprofile = "p"').profile, "p")
        # a profile no command names is still a string without NUL
        self.refused("[agent] profile", agent='preset = "codex"\nprofile = "a\\u0000b"')

    def test_remote_and_base_hold_no_nul_and_are_strings(self):
        for key, bad in [
            ("remote", '"https://github.com/acme/lib.git\\u0000"'),
            ("remote", "5"),
            ("base", '"ma\\u0000in"'),
            ("base", "5"),
            ("base", '""'),
        ]:
            tail = f'[repos.lib]\nremote = "https://github.com/acme/lib.git"\n{key} = {bad}\n'
            if key == "remote":
                tail = f'[repos.lib]\n{key} = {bad}\ngithub = "acme/lib"\n'
            path = self.rig.checkout / ".gonk" / "worker.toml"
            path.write_text(
                f'routers = {json.dumps([DISPATCHER])}\nlabels = ["worker:w1"]\n'
                f'[agent]\npreset = "codex"\n\n{tail}'
            )
            with self.assertRaises(gonk.ConfigError, msg=f"{key} = {bad}") as ctx:
                worker.load_worker(gonk.load(self.rig.checkout))
            self.assertIn(f"[repos.lib] {key}", str(ctx.exception))
            self.assertIn("worker.toml", str(ctx.exception))

    def test_paths_hold_no_nul(self):
        self.refused("work_root", top='work_root = "~/a\\u0000b"')
        self.refused("stop_file", top='stop_file = "/tmp/a\\u0000b"')


if __name__ == "__main__":
    unittest.main()
