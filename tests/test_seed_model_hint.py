"""The spec chooses the model: `gonk.py seed` reads `[haiku|sonnet|opus]` and an optional
`repo:<name>` after a task's number (dax-routes, design D6)."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import gonk  # noqa: E402  (the path above)

IDEOGRAPHIC_SPACE = "　"
ZERO_WIDTH_SPACE = "​"
BOM = "﻿"


class FakeIkigai:
    def __init__(self) -> None:
        self.appended: list[tuple[str, str]] = []

    def run(self, command: str, stdin: str | None = None):
        n = len(self.appended) + 1
        if "append" in command.split()[1]:
            self.appended.append((command, stdin or ""))
            return SimpleNamespace(
                ok=True, out=f"carducci#{n} urn:fake:{n}", code=0, text=lambda: ""
            )
        return SimpleNamespace(ok=True, out="", code=0, text=lambda: "")


def run_seed(
    tasks: str,
    remote: str | None = "https://github.com/carducci/ikigraph.git",
    folder: str = "somedir",
    others: dict[str, str] | None = None,
    changes: list[str] | None = None,
    dry_run: bool = False,
    path: str | None = None,
    git_config: dict[str, str] | None = None,
):
    """Seed a repository whose change `x` has tasks.md `tasks` (and `others`, change -> tasks.md):
    (exit code, appends, error, stdout)."""
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / folder
        for name, text in {"x": tasks, **(others or {})}.items():
            change = repo / "openspec" / "changes" / name
            change.mkdir(parents=True)
            (change / "tasks.md").write_text(text, encoding="utf-8")
        layout = {"spec": [{"format": "openspec", "root": "openspec"}]}
        if remote:
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote], check=True)
            for key, value in (git_config or {}).items():
                subprocess.run(["git", "-C", str(repo), "config", key, value], check=True)
        cfg = gonk.Config(repo, "carducci", object(), "h", layout)
        fake = FakeIkigai()
        args = SimpleNamespace(changes=changes or [], dry_run=dry_run)
        err = ""
        code = 0
        out = io.StringIO()
        saved = os.environ["PATH"]
        try:
            if path is not None:
                os.environ["PATH"] = path
            with contextlib.redirect_stdout(out):
                code = gonk.cmd_seed(args, cfg, lambda target: fake)
        except gonk.ConfigError as e:
            code, err = 2, str(e)
        finally:
            os.environ["PATH"] = saved
        return code, fake.appended, err, out.getvalue()


def seed(tasks: str, remote: str | None = "https://github.com/carducci/ikigraph.git", **kw):
    """(exit code, appends, error) of `run_seed`."""
    return run_seed(tasks, remote, **kw)[:3]


def labels_of(command: str) -> list[str]:
    word = next(w for w in command.split() if w.startswith("labels="))
    return word[len("labels=") :].split(",")


class SeedModelHint(unittest.TestCase):
    def test_a_hinted_task(self):
        code, appended, _ = seed("- [ ] 2.1 [sonnet] Add x (Some requirement)\n")
        self.assertEqual(0, code)
        ((command, content),) = appended
        self.assertIn("agent:claude-sonnet", labels_of(command))
        self.assertIn("repo:ikigraph", labels_of(command))
        self.assertTrue(content.startswith("x 2.1: Add x\n"), content)
        self.assertNotIn("[sonnet]", content)

    def test_a_task_in_another_repository(self):
        code, appended, _ = seed("- [ ] 1.2 [haiku repo:ikigai-gonk-starter] Do y (R)\n")
        self.assertEqual(0, code)
        ((command, content),) = appended
        labels = labels_of(command)
        self.assertIn("agent:claude-haiku", labels)
        self.assertIn("repo:ikigai-gonk-starter", labels)
        self.assertNotIn("repo:ikigraph", labels)
        self.assertNotIn("repo:", content.split("\n")[0])

    def test_a_misspelt_model_files_nothing_and_names_the_line(self):
        code, appended, err = seed("- [ ] 1.1 [opus] Fine\n- [ ] 1.2 [sonet] Typo (R)\n")
        self.assertEqual(2, code)
        self.assertEqual([], appended)
        self.assertIn("tasks.md:2", err)
        self.assertIn("sonet", err)

    def test_an_unknown_word_after_the_model_is_refused(self):
        code, appended, err = seed("- [ ] 1.1 [sonnet repoo:a] T\n")
        self.assertEqual(2, code)
        self.assertEqual([], appended)
        self.assertIn("tasks.md:1", err)

    def test_a_task_with_no_brackets_has_no_agent_label(self):
        code, appended, _ = seed("- [ ] 3.1 Decide the thing (human: Michael)\n")
        self.assertEqual(0, code)
        ((command, content),) = appended
        self.assertEqual(["change:x"], labels_of(command))
        self.assertTrue(content.startswith("x 3.1: Decide the thing\n"), content)

    def test_the_default_repository_is_the_origin_name_without_dot_git(self):
        _, appended, _ = seed("- [ ] 1.1 [opus] T\n", remote="git@github.com:carducci/MagoTech.git")
        self.assertIn("repo:MagoTech", labels_of(appended[0][0]))

    def test_a_hint_on_a_human_task_is_refused(self):
        code, appended, err = seed("- [ ] 4.1 [opus] Merge the PRs (human: Michael)\n")
        self.assertEqual(2, code)
        self.assertEqual([], appended)
        self.assertIn("tasks.md:1", err)

    def test_a_bad_hint_on_a_done_task_is_not_refused(self):
        code, appended, _ = seed("- [x] 1.1 [sonet] old\n- [ ] 1.2 [opus] new\n")
        self.assertEqual(0, code)
        self.assertEqual(1, len(appended))
        self.assertIn("x 1.2: new", appended[0][1])

    def test_a_bad_hint_in_any_change_seeded_is_refused(self):
        code, appended, err = seed(
            "- [ ] 1.1 [opus] fine\n", others={"b": "- [ ] 1.1 [sonet] bad\n"}
        )
        self.assertEqual(2, code)
        self.assertEqual([], appended)
        self.assertIn("b/tasks.md:1", err)

    def test_open_changes_does_not_refuse_on_a_hint(self):
        with tempfile.TemporaryDirectory() as d:
            change = Path(d) / "openspec" / "changes" / "x"
            change.mkdir(parents=True)
            (change / "tasks.md").write_text("- [x] 1.1 [sonet] old\n", encoding="utf-8")
            layout = {"spec": [{"format": "openspec", "root": "openspec"}]}
            got = gonk.open_changes(Path(d), layout)
        self.assertEqual(1, len(got[0].tasks))

    def test_a_markdown_link_is_not_a_hint(self):
        code, appended, _ = seed("- [ ] 1.1 [README](README.md): say what the tool does\n")
        self.assertEqual(0, code)
        self.assertTrue(appended[0][1].startswith("x 1.1: [README](README.md): say what"))
        self.assertEqual(["change:x"], labels_of(appended[0][0]))

    def test_the_title_has_no_leading_whitespace_after_the_hint(self):
        for sep in ("\t", IDEOGRAPHIC_SPACE, "  "):
            with self.subTest(sep=sep):
                _, appended, _ = seed(f"- [ ] 1.1 [sonnet]{sep}Add x (R)\n")
                self.assertTrue(appended[0][1].startswith("x 1.1: Add x\n"), appended[0][1])

    def test_the_title_has_no_whitespace_at_its_ends_once_the_citation_is_removed(self):
        sp = IDEOGRAPHIC_SPACE
        for line in (
            f"- [ ] 1.1 [sonnet] Add x{sp}(R)",
            f"- [ ] 1.1 Add x{sp}(R)",
            "- [ ] 1.1 \tAdd x",
        ):
            with self.subTest(line=line):
                _, appended, _ = seed(line + "\n")
                self.assertTrue(appended[0][1].startswith("x 1.1: Add x\n"), appended[0][1])

    def test_a_hint_with_no_text_is_refused(self):
        code, appended, err = seed("- [ ] 1.1 [sonnet]\n")
        self.assertEqual(2, code)
        self.assertEqual([], appended)
        self.assertIn("tasks.md:1", err)

    def test_an_origin_ending_in_a_slash_or_dot_git_slash(self):
        for remote in (
            "https://github.com/carducci/ikigraph/",
            "git@github.com:carducci/ikigraph.git/",
            "https://github.com/carducci/ikigraph.git",
        ):
            with self.subTest(remote=remote):
                _, appended, _ = seed("- [ ] 1.1 [opus] T\n", remote=remote, folder="item-1067")
                self.assertIn("repo:ikigraph", labels_of(appended[0][0]))

    def test_a_folder_name_that_is_no_repo_name_is_refused(self):
        for folder in ("My Repo", "a,b"):
            with self.subTest(folder=folder):
                code, appended, err = seed("- [ ] 1.1 [opus] T\n", remote=None, folder=folder)
                self.assertEqual(2, code)
                self.assertEqual([], appended)
                self.assertIn("repo", err)

    def test_the_folder_names_the_repository_when_there_is_no_origin(self):
        _, appended, _ = seed("- [ ] 1.1 [opus] T\n", remote=None, folder="my-folder")
        self.assertIn("repo:my-folder", labels_of(appended[0][0]))

    def test_a_second_repo_word_is_refused(self):
        code, appended, _ = seed("- [ ] 1.1 [opus repo:a repo:b] T\n")
        self.assertEqual(2, code)
        self.assertEqual([], appended)

    def test_a_repo_name_must_have_the_shape_of_one(self):
        for word in ("repo:../x", "repo:", "repo:a,b"):
            with self.subTest(word=word):
                code, appended, _ = seed(f"- [ ] 1.1 [opus {word}] T\n")
                self.assertEqual(2, code)
                self.assertEqual([], appended)

    def test_a_missing_git_is_no_origin(self):
        code, _, err, out = run_seed(
            "- [ ] 1.1 T\n", remote=None, dry_run=True, path="/nonexistent"
        )
        self.assertEqual(0, code, err)
        self.assertIn("would file  x 1.1: T", out)
        code, appended, _, _ = run_seed(
            "- [ ] 1.1 [opus] T\n", remote=None, folder="my-folder", path="/nonexistent"
        )
        self.assertEqual(0, code)
        self.assertIn("repo:my-folder", labels_of(appended[0][0]))

    def test_the_dry_run_shows_the_labels(self):
        _, _, _, out = run_seed("- [ ] 1.1 [sonnet repo:other] T\n", dry_run=True)
        self.assertIn("agent:claude-sonnet", out)
        self.assertIn("repo:other", out)
        self.assertIn("change:x", out)

    def test_a_hinted_task_with_only_a_requirement_has_no_title_and_is_refused(self):
        for line in (
            "- [ ] 1.1 [sonnet] (Some requirement)",
            f"- [ ] 1.1 [sonnet]{IDEOGRAPHIC_SPACE}(R)",
        ):
            with self.subTest(line=line):
                code, appended, err = seed(line + "\n")
                self.assertEqual(2, code)
                self.assertEqual([], appended)
                self.assertIn("tasks.md:1", err)

    def test_an_untitled_done_task_is_not_refused(self):
        code, appended, _ = seed("- [x] 1.1 [sonnet] (R)\n- [ ] 1.2 T\n")
        self.assertEqual(0, code)
        self.assertEqual(1, len(appended))

    def test_a_human_note_is_recognised_however_it_is_parenthesised(self):
        for note in ("(human: Michael (PM))", "(human: a (b) (c))", "( human: Michael)"):
            with self.subTest(note=note):
                code, appended, err = seed(f"- [ ] 4.1 [opus] Merge {note}\n")
                self.assertEqual(2, code)
                self.assertEqual([], appended)
                self.assertIn("tasks.md:1", err)

    def test_a_hinted_human_task_followed_by_its_citation_is_refused(self):
        # The form the changes write: `(human: ...)` then `(Requirement)`, as dax-routes 4.1.
        code, appended, err = seed("- [ ] 4.1 [opus] Merge (human: Michael) (Some requirement)\n")
        self.assertEqual(2, code)
        self.assertEqual([], appended)
        self.assertIn("tasks.md:1", err)

    def test_a_human_note_is_recognised_in_any_case_and_with_space_before_the_colon(self):
        for note in ("(human : Michael)", "(Human: Michael)", "(HUMAN : Michael)"):
            with self.subTest(note=note):
                code, appended, err = seed(f"- [ ] 1.1 [opus] Merge {note}\n")
                self.assertEqual(2, code)
                self.assertEqual([], appended)
                self.assertIn("tasks.md:1", err)

    def test_a_title_made_only_of_format_characters_is_refused(self):
        for line in (
            f"- [ ] 1.1 [opus] {ZERO_WIDTH_SPACE}",
            f"- [ ] 1.1 [opus] {ZERO_WIDTH_SPACE}(R)",
            f"- [ ] 1.1 {ZERO_WIDTH_SPACE}{BOM}",
        ):
            with self.subTest(line=line):
                code, appended, err = seed(line + "\n")
                self.assertEqual(2, code)
                self.assertEqual([], appended)
                self.assertIn("tasks.md:1", err)

    def test_a_nested_human_task_without_a_hint_is_filed_with_no_agent_label(self):
        code, appended, _ = seed("- [ ] 4.1 Merge (human: Michael (PM))\n")
        self.assertEqual(0, code)
        self.assertEqual(["change:x"], labels_of(appended[0][0]))

    def test_a_task_that_only_mentions_human_in_its_text_may_be_hinted(self):
        code, appended, _ = seed("- [ ] 4.1 [opus] Ask the human: who (R)\n")
        self.assertEqual(0, code)
        self.assertIn("agent:claude-opus", labels_of(appended[0][0]))

    def test_a_repository_with_no_name_files_unhinted_tasks(self):
        code, appended, err = seed("- [ ] 1.1 T\n", remote=None, folder="My Repo")
        self.assertEqual(0, code, err)
        self.assertTrue(appended[0][1].startswith("x 1.1: T\n"))
        code, _, _, _ = run_seed("- [ ] 1.1 [opus repo:o] T\n", remote=None, folder="My Repo")
        self.assertEqual(0, code)
        code, _, _, _ = run_seed("- [ ] 1.1 T\n", remote=None, folder="My Repo", dry_run=True)
        self.assertEqual(0, code)

    def test_a_hint_without_repo_needs_a_name_even_when_another_task_names_its_repo(self):
        code, _, _ = seed(
            "- [ ] 1.1 [opus repo:o] A\n- [ ] 1.2 [opus] B\n", remote=None, folder="My Repo"
        )
        self.assertEqual(2, code)

    def test_a_human_note_in_any_position_or_form_refuses_a_hinted_task(self):
        # Finding 1 of round 1: the note need not end the line, nor use parentheses or `:`.
        for text in (
            "[opus] Merge the PRs (human: Michael).",
            "[opus] (human: Michael) Merge the PRs",
            "[opus] Merge (human: Michael) for x",
            "[opus] Merge [human: Michael] (R)",
            "[opus] Merge (human： Michael)",
            "[opus] Merge [Human ： Michael]",
        ):
            with self.subTest(text=text):
                code, appended, err = seed(f"- [ ] 4.1 {text}\n")
                self.assertEqual(2, code)
                self.assertEqual([], appended)
                self.assertIn("tasks.md:1", err)

    def test_an_unhinted_human_task_in_any_form_has_no_agent_or_repo_label(self):
        for text in ("Merge (human： Michael)", "(human: M) Merge", "Merge [human: M] (R)"):
            with self.subTest(text=text):
                code, appended, _ = seed(f"- [ ] 4.1 {text}\n")
                self.assertEqual(0, code)
                self.assertEqual(["change:x"], labels_of(appended[0][0]))

    def test_the_default_repository_is_the_last_segment_of_any_origin(self):
        for remote in (
            "git@github-work:carducci/ikigraph.git",
            "ssh://git@ssh.github.com:443/carducci/ikigraph.git",
            "https://gitlab.com/carducci/ikigraph.git",
            "/srv/git/ikigraph.git",
            "/srv/git/ikigraph/",
            "host:ikigraph.git",
        ):
            with self.subTest(remote=remote):
                _, appended, _ = seed("- [ ] 1.1 [opus] T\n", remote=remote, folder="item-1338")
                self.assertIn("repo:ikigraph", labels_of(appended[0][0]))

    def test_the_origin_is_read_through_insteadof(self):
        _, appended, _ = seed(
            "- [ ] 1.1 [opus] T\n",
            remote="work:thing",
            folder="item-1338",
            git_config={"url.https://example.com/carducci/ikigraph.git.insteadOf": "work:thing"},
        )
        self.assertIn("repo:ikigraph", labels_of(appended[0][0]))

    def test_a_known_model_followed_at_once_by_a_paren_is_refused(self):
        for text in (
            "1.1 [opus](R)",
            "1.1 [sonnet](x) Add y",
            "1.1 [haiku repo:other](x) Add y",
            "1.1 [opus repo:other](R)",
        ):
            with self.subTest(text=text):
                code, appended, err = seed(f"- [ ] {text}\n")
                self.assertEqual(2, code)
                self.assertEqual([], appended)
                self.assertIn("tasks.md:1", err)

    def test_any_other_bracket_paren_stays_a_link(self):
        for text in ("[README](README.md) Do x", "[opusx](u) Do x", "[opus foo](u) Do x"):
            with self.subTest(text=text):
                code, appended, _ = seed(f"- [ ] 1.1 {text}\n")
                self.assertEqual(0, code)
                self.assertEqual(["change:x"], labels_of(appended[0][0]))


if __name__ == "__main__":
    unittest.main()
