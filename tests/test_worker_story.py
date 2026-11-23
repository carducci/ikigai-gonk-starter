"""The worker's stories (tools/worker.py, worker/README.md "Stories"): one whole OpenSpec change
applied by one agent session. Hermetic: the in-memory ledger, a real git origin with a change in
it, the stub gh, the fake agent (`--tick`, `--hang`), a fake `openspec` on PATH and a fake build."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shlex
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support import gonk
from worker_support import FAKES, FakeLedger, Rig, git, worker

CHANGE = "add-widget"
BRANCH = f"story/{CHANGE}"


def story_labels(*changes: str) -> list[str]:
    return ["worker:w1", "repo:lib", "story", *(f"change:{c}" for c in changes)]


class StoryRig:
    """A rig whose origin's main has the change `add-widget`, with three open tasks."""

    def __init__(self, test: unittest.TestCase, tasks: int = 3) -> None:
        self.test = test
        self.rig = Rig(test)
        self.ledger = FakeLedger()
        self.seed = self.rig.tmp / "seed"
        change = self.seed / "openspec" / "changes" / CHANGE
        change.mkdir(parents=True)
        (change / "proposal.md").write_text("# Add a widget\n")
        (change / "tasks.md").write_text(
            "".join(f"- [ ] {i}. Task {i}\n" for i in range(1, tasks + 1))
        )
        git("add", "openspec", cwd=self.seed)
        git("commit", "-q", "-m", "Propose add-widget", cwd=self.seed)
        git("push", "-q", str(self.rig.origin), "main", cwd=self.seed)
        # The fake openspec, as `openspec` on PATH for the worker's checks.
        bin_dir = self.rig.tmp / "bin"
        bin_dir.mkdir()
        wrapper = bin_dir / "openspec"
        wrapper.write_text(
            f"#!/bin/sh\nexec {shlex.quote(sys.executable)} "
            f'{shlex.quote(str(FAKES / "openspec.py"))} "$@"\n'
        )
        wrapper.chmod(0o755)
        path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        patcher = mock.patch.dict(os.environ, {"PATH": path})
        patcher.start()
        test.addCleanup(patcher.stop)

    @staticmethod
    def build(status: str = "pass", code: int = 0) -> str:
        """A `[story] build` line running the fake build."""
        argv = [sys.executable, str(FAKES / "fake_build.py"), "--status", status]
        return f"build = {json.dumps([*argv, '--exit', str(code)])}"

    def story(self, body: str = "Apply add-widget.") -> int:
        return self.ledger.file("Build the widget", story_labels(CHANGE), body=body)

    def run(self, *flags: str, story: str | None = None, **configure):
        self.rig.agent_flags = ["--change", CHANGE, *flags]
        self.rig.configure(story=story, **configure)
        self.worker = self.rig.worker(self.ledger)
        return self.worker.run_once()

    def origin_head(self, branch: str) -> str:
        return git("rev-parse", branch, cwd=self.rig.origin).strip()

    def tree(self, number: int) -> Path:
        return self.rig.home / "work" / "lib" / f"item-{number}"


class TellingAStory(unittest.TestCase):
    def test_one_change_label_makes_a_story(self):
        item = {"labels": story_labels(CHANGE)}
        self.assertTrue(worker.is_story(item))
        self.assertEqual(worker.story_change(item), CHANGE)
        self.assertIsNone(worker.story_problem(item))

    def test_an_item_without_the_story_label_is_no_story_and_no_problem(self):
        item = {"labels": ["worker:w1", "repo:lib", f"change:{CHANGE}"]}
        self.assertFalse(worker.is_story(item))
        self.assertIsNone(worker.story_problem(item))

    def test_no_change_two_changes_or_a_bad_id_is_a_problem(self):
        for changes, said in (
            ((), "none"),
            (("a", "b"), "change:a, change:b"),
            (("Add_Widget",), "'Add_Widget'"),
            (("-lead",), "'-lead'"),
            (("x" * 65,), "is not a change id"),
        ):
            item = {"labels": story_labels(*changes)}
            self.assertFalse(worker.is_story(item), changes)
            self.assertIn(said, worker.story_problem(item), changes)


class TheStoryTable(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(self)

    def load(self, story: str | None):
        cfg = gonk.load(self.rig.checkout)
        return worker.load_worker(cfg, self.rig.configure(story=story)).story

    def test_without_one_it_has_the_defaults(self):
        story = self.load(None)
        self.assertEqual((story["stall"], story["check"]), (1800, 60))
        self.assertIsNone(story["build"])
        self.assertEqual(story["ui_globs"], [])
        self.assertEqual(story["evidence"], "openspec/changes/{change}/evidence/screenshots")

    def test_its_settings_are_read(self):
        story = self.load(
            'stall = "5m"\ncheck = "10s"\nbuild = "just gates"\nui_globs = ["web/**"]\n'
            'evidence = "docs/shots/{change}"'
        )
        self.assertEqual((story["stall"], story["check"]), (300, 10))
        self.assertEqual(story["build"], ["just", "gates"])
        self.assertEqual(story["ui_globs"], ["web/**"])
        self.assertEqual(story["evidence"], "docs/shots/{change}")

    def test_what_it_refuses(self):
        for bad in (
            'colour = "red"',
            "build = []",
            "build = [1]",
            'ui_globs = "web/**"',
            'evidence = "/abs"',
            'evidence = "../out"',
            'stall = "soon"',
            'check = "0s"',
        ):
            with self.subTest(bad), self.assertRaises(gonk.ConfigError):
                self.load(bad)


class Selection(unittest.TestCase):
    def setUp(self):
        self.rig, self.ledger = Rig(self), FakeLedger()

    def test_a_story_naming_no_change_or_two_is_skipped_saying_why(self):
        self.ledger.file("No change", story_labels())
        self.ledger.file("Two changes", story_labels("a", "b"))
        self.rig.configure()
        w = self.rig.worker(self.ledger)
        take, skip, err = w.candidates()
        self.assertIsNone(err)
        self.assertEqual(take, [])
        self.assertEqual([d for d, _ in skip], ["acme#1", "acme#2"])
        self.assertIn("exactly one OpenSpec change", skip[1][1])
        self.assertEqual(w.run_once().code, worker.NOTHING)

    def test_a_small_items_loop_without_story_never_sees_one(self):
        self.ledger.file("A story", story_labels(CHANGE))
        plain = self.ledger.file("A small item", ["worker:w1", "repo:lib"])
        self.rig.configure(without='["story"]')
        w = self.rig.worker(self.ledger)
        take, skip, _ = w.candidates()
        self.assertEqual([i["number"] for i, _ in take], [plain])
        self.assertEqual(skip, [])
        self.assertEqual(w.why_not(self.ledger.items[plain], datetime.now(UTC), {}), None)


class TheBrief(unittest.TestCase):
    def setUp(self):
        self.s = StoryRig(self)

    def test_a_story_runs_under_the_story_preamble(self):
        n = self.s.story()
        self.s.run(story='build = ["just", "gates", "{change}"]\nstall = "20m"')
        prompt = self.s.rig.prompt(n)
        for said in (
            "You are an unattended builder",
            f"Apply the OpenSpec change `{CHANGE}`",
            ".claude/skills/openspec-apply-change",
            f"openspec instructions apply --change {CHANGE}",
            f"openspec/changes/{CHANGE}/explore.md",
            "Resume at the first unticked task",
            f"on the branch story/{CHANGE}",
            "draft pull request against main",
            "`just gates add-widget`",
            "nothing has moved for\n   20m00s",
            f"openspec/changes/{CHANGE}/evidence/screenshots/",
            "NEVER mark the pull request ready",
            "Question for Dax:",
            "Apply add-widget.",
        ):
            self.assertIn(said, prompt)
        self.assertNotIn("gh pr create", prompt)
        self.assertEqual(re.findall(r"\{[a-z_]+\}", prompt), [], "every token is filled in")

    def test_without_a_build_it_says_none_is_configured(self):
        n = self.s.story()
        self.s.run()
        self.assertIn("none is configured for the worker", self.s.rig.prompt(n))

    def test_a_plain_item_keeps_the_change_preamble(self):
        n = self.s.ledger.file("Small", ["worker:w1", "repo:lib"])
        self.s.run()
        prompt = self.s.rig.prompt(n)
        self.assertIn("You are an unattended worker", prompt)
        self.assertNotIn("OpenSpec change", prompt)


class TheBranch(unittest.TestCase):
    def setUp(self):
        self.s = StoryRig(self)

    def test_a_new_story_starts_from_main_on_its_own_branch(self):
        n = self.s.story()
        main = self.s.origin_head("main")
        self.s.run()
        self.assertEqual((self.s.rig.record / f"head-{n}").read_text(), main)
        self.assertIn(f"story/{CHANGE}", self.s.rig.branches())

    def test_a_story_resumes_from_its_branch_on_origin(self):
        seed = self.s.seed
        tasks = seed / "openspec" / "changes" / CHANGE / "tasks.md"
        tasks.write_text(tasks.read_text().replace("- [ ]", "- [x]", 1))
        git("commit", "-q", "-am", "Tick task 1", cwd=seed)
        git("push", "-q", str(self.s.rig.origin), f"HEAD:refs/heads/story/{CHANGE}", cwd=seed)
        resumed = self.s.origin_head(f"story/{CHANGE}")
        n = self.s.story()
        self.s.run()
        self.assertEqual((self.s.rig.record / f"head-{n}").read_text(), resumed)

    def test_its_own_kept_worktree_is_pushed_then_removed_and_the_next_run_resumes(self):
        n = self.s.story()
        self.s.run("--no-pr", "--tick", "1")  # no evidence: the worktree is kept
        ticked = git("rev-parse", "HEAD", cwd=self.s.tree(n)).strip()
        self.s.worker.attempts.forget("acme", n)
        self.s.run("--no-pr")
        self.assertEqual((self.s.rig.record / f"head-{n}").read_text(), ticked)
        self.assertEqual(self.s.origin_head(f"story/{CHANGE}"), ticked)
        self.assertFalse((self.s.rig.home / "work" / "lib" / f"item-{n}.2").exists())


class Supervision(unittest.TestCase):
    def setUp(self):
        self.s = StoryRig(self)

    def drafts(self) -> list[dict]:
        return [pr for pr in self.s.rig.gh().get("prs", []) if pr["headRefName"] == BRANCH]

    def creates(self) -> list[list[str]]:
        return [c for c in self.s.rig.gh().get("calls", []) if c[:2] == ["pr", "create"]]

    def test_ticks_are_pushed_to_one_draft_pull_request_and_a_stall_stops_it(self):
        n = self.s.story()
        outcome = self.s.run(
            "--no-pr", "--tick", "2", "--tick-every", "1.5", "--hang",
            story='check = "1s"\nstall = "4s"',
        )  # fmt: skip
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn("it stalled: no new commit and no task ticked for 0m04s", outcome.summary)
        last_tick = git("rev-parse", "HEAD", cwd=self.s.tree(n)).strip()
        self.assertEqual(self.s.origin_head(BRANCH), last_tick)
        self.assertEqual(len(self.creates()), 1)
        (draft,) = self.drafts()
        self.assertTrue(draft["isDraft"])
        self.assertEqual(draft["baseRefName"], "main")
        self.assertIn("--draft", self.creates()[0])
        self.assertEqual(self.s.rig.gh()["forbidden"], [])

    def test_an_agent_that_changes_nothing_is_stopped_with_nothing_pushed(self):
        n = self.s.story()
        outcome = self.s.run("--no-pr", "--hang", story='check = "1s"\nstall = "2s"')
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertIn("stalled", outcome.summary)
        self.assertTrue((self.s.rig.record / f"hanging-{n}").exists())
        self.assertNotIn(BRANCH, self.s.rig.branches())
        self.assertEqual(self.creates(), [])

    def test_a_refused_push_is_logged_and_never_forced(self):
        tree = self.s.rig.tmp / "clone"
        git("clone", "-q", str(self.s.rig.origin), str(tree))
        git("checkout", "-q", "-b", BRANCH, cwd=tree)
        (tree / "mine.txt").write_text("mine\n")
        git("add", "mine.txt", cwd=tree)
        git("commit", "-q", "-m", "Mine", cwd=tree)
        (self.s.seed / "theirs.txt").write_text("theirs\n")
        git("add", "theirs.txt", cwd=self.s.seed)
        git("commit", "-q", "-m", "Theirs", cwd=self.s.seed)
        git("push", "-q", str(self.s.rig.origin), f"HEAD:refs/heads/{BRANCH}", cwd=self.s.seed)
        theirs = self.s.origin_head(BRANCH)
        gh = worker.GitHub(self.s.rig.gh_argv, "acme/lib")
        ws = SimpleNamespace(path=tree, branch=BRANCH)
        watch = worker.StoryWatch(ws, CHANGE, gh, "main", 60, 1, "t", "b")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertFalse(watch.checkpoint())
        self.assertIn("refused the push", out.getvalue())
        self.assertEqual(watch.refused, 1)
        self.assertEqual(self.s.origin_head(BRANCH), theirs)
        self.assertNotIn("calls", self.s.rig.gh())


class TheChecks(unittest.TestCase):
    def setUp(self):
        self.s = StoryRig(self)

    def draft(self) -> dict:
        (pr,) = [pr for pr in self.s.rig.gh().get("prs", []) if pr["headRefName"] == BRANCH]
        return pr

    def said(self, number: int) -> str:
        return "\n".join(c["text"] for c in self.s.ledger.human_comments(number))

    def test_every_check_passes_so_the_pull_request_is_ready_and_handed_back(self):
        n = self.s.story()
        outcome = self.s.run("--no-pr", "--tick", "3", story=self.s.build("pass"))
        self.assertEqual(outcome.code, worker.HANDED_BACK, outcome.summary)
        pr = self.draft()
        self.assertFalse(pr["isDraft"])
        said = self.said(n)
        self.assertTrue(said.startswith(f"Evidence: {pr['url']}\n"), said)
        for line in (
            f"- validate: pass `openspec validate {CHANGE} --strict` exited 0",
            "- tasks: pass all 3 tasks ticked",
            "- build: pass",
            "- screenshots: pass not required (no [story] ui_globs)",
            "Every check passed: it marked",
        ):
            self.assertIn(line, said)
        item = self.s.ledger.items[n]
        self.assertEqual(item["awaiting"], "dispatcher")
        self.assertIsNone(item["claim"])
        self.assertEqual(self.s.ledger.closes, [])
        self.assertEqual(self.s.rig.gh()["forbidden"], [])
        self.assertFalse(self.s.tree(n).exists())

    def assert_stays_a_draft(self, number: int, outcome, *lines: str) -> str:
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        self.assertTrue(self.draft()["isDraft"])
        said = self.said(number)
        self.assertNotIn("Evidence:", said)
        self.assertIn("The pull request stays a draft", said)
        for line in lines:
            self.assertIn(line, said)
        item = self.s.ledger.items[number]
        self.assertIsNone(item["awaiting"])
        self.assertIsNone(item["claim"])
        calls = [c[:2] for c in self.s.rig.gh()["calls"] if "--undo" not in c]
        self.assertNotIn(["pr", "ready"], calls)
        self.assertTrue(self.s.tree(number).exists())
        return said

    def test_a_failing_build_keeps_the_draft(self):
        n = self.s.story()
        outcome = self.s.run("--no-pr", "--tick", "3", story=self.s.build("fail"))
        self.assert_stays_a_draft(
            n, outcome, "- build: FAIL", "AGENT-BUILD-RESULT status 'fail'", "- tasks: pass"
        )

    def test_a_build_that_exits_non_zero_or_says_nothing_fails(self):
        for build, said in (
            (self.s.build("pass", 2), "exited 2"),
            (self.s.build("none"), "printed no AGENT-BUILD-RESULT line"),
            (self.s.build("garbled"), "is not JSON"),
        ):
            with self.subTest(said):
                s = StoryRig(self)
                n = s.story()
                outcome = s.run("--no-pr", "--tick", "3", story=build)
                self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
                text = "\n".join(c["text"] for c in s.ledger.human_comments(n))
                self.assertIn("- build: FAIL", text)
                self.assertIn(said, text)

    def test_unticked_tasks_keep_the_draft(self):
        n = self.s.story()
        outcome = self.s.run("--no-pr", "--tick", "1", story=self.s.build("pass"))
        self.assert_stays_a_draft(n, outcome, "- tasks: FAIL 2 of 3 tasks unticked")

    def test_a_change_that_does_not_validate_keeps_the_draft(self):
        n = self.s.story()
        with mock.patch.dict(os.environ, {"FAKE_OPENSPEC": "fail"}):
            outcome = self.s.run("--no-pr", "--tick", "3", story=self.s.build("pass"))
        self.assert_stays_a_draft(n, outcome, "- validate: FAIL", "missing or invalid")

    def test_no_build_configured_is_said_and_does_not_pass(self):
        n = self.s.story()
        outcome = self.s.run("--no-pr", "--tick", "3")
        self.assert_stays_a_draft(n, outcome, "- build: not configured")

    def test_a_question_for_dax_reaches_the_item(self):
        n = self.s.story()
        question = "Question for Dax: should the widget be blue?"
        outcome = self.s.run("--no-pr", "--tick", "1", "--report", question)
        self.assert_stays_a_draft(n, outcome, "The agent's report:", question)

    def test_ui_work_without_a_screenshot_keeps_the_draft(self):
        n = self.s.story()
        # The fake agent's own commit (WORKED.txt) is the UI path here.
        outcome = self.s.run(
            "--tick", "3", story=self.s.build("pass") + '\nui_globs = ["WORKED.*"]'
        )
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        said = self.said(n)
        self.assertIn("- screenshots: FAIL UI paths changed (WORKED.txt)", said)
        self.assertIn(f"openspec/changes/{CHANGE}/evidence/screenshots has no PNG", said)

    def test_ui_work_with_a_screenshot_passes(self):
        tree = self.s.rig.tmp / "clone"
        git("clone", "-q", str(self.s.rig.origin), str(tree))
        shots = tree / "openspec" / "changes" / CHANGE / "evidence" / "screenshots"
        shots.mkdir(parents=True)
        (shots / "empty.png").write_bytes(b"\x89PNG\r\n")
        (tree / "web").mkdir()
        (tree / "web" / "page.html").write_text("<p>widget</p>\n")
        git("add", ".", cwd=tree)
        git("commit", "-q", "-m", "A page", cwd=tree)
        table = worker.load_story({"ui_globs": ["web/*"]}, "test")
        ws = SimpleNamespace(path=tree, branch=BRANCH)
        checks = {c.name: c for c in worker.story_checks(ws, CHANGE, "main", table)}
        where = shots.relative_to(tree).as_posix()
        self.assertEqual(checks["screenshots"].line, f"- screenshots: pass 1 PNG in {where}")
        (shots / "empty.png").unlink()
        checks = {c.name: c for c in worker.story_checks(ws, CHANGE, "main", table)}
        self.assertIn("UI paths changed (web/page.html)", checks["screenshots"].line)

    def test_a_stalled_story_keeps_its_draft_and_says_why(self):
        n = self.s.story()
        outcome = self.s.run(
            "--no-pr", "--tick", "3", "--hang",
            story=self.s.build("pass") + '\ncheck = "1s"\nstall = "2s"',
        )  # fmt: skip
        said = self.assert_stays_a_draft(n, outcome, "- tasks: pass", "- build: pass")
        self.assertIn("it stalled: no new commit and no task ticked for 0m02s", said)
        self.assertIn("Left a draft: the agent stalled.", said)


class CountingAgainstStories(unittest.TestCase):
    """Under max_per_repo a story counts only against stories (as a review only against
    reviews), so a builder with max_per_repo 1 runs beside two coders of its repository."""

    def setUp(self):
        self.s = StoryRig(self)

    def coders_hold_two_items(self) -> None:
        for name in ("coder-1", "coder-2"):
            n = self.s.ledger.file(f"Fix for {name}", ["worker:w1", "repo:lib"])
            self.s.ledger.force_claim(n, name)

    def test_a_builder_takes_a_story_while_two_coders_hold_items_of_its_repository(self):
        self.coders_hold_two_items()
        n = self.s.story()
        outcome = self.s.run("--no-pr", "--tick", "3", story=self.s.build(), max_per_repo="1")
        self.assertEqual(outcome.code, worker.HANDED_BACK, outcome.summary)
        self.assertEqual(outcome.number, n)

    def test_a_claimed_story_still_fences_a_second_story(self):
        first = self.s.story()
        self.s.ledger.force_claim(first, "builder-2")
        second = self.s.story()
        self.s.rig.configure(max_per_repo="1")
        w = self.s.rig.worker(self.s.ledger)
        take, skip, _ = w.candidates()
        self.assertEqual(take, [])
        why = dict(skip)[f"acme#{second}"]
        self.assertIn("is claimed by `builder-2`", why)
        self.assertIn("counting stories only", why)

    def test_a_builders_story_does_not_fence_a_coder(self):
        story = self.s.story()
        self.s.ledger.force_claim(story, "builder")
        fix = self.s.ledger.file("A fix", ["worker:w1", "repo:lib"])
        self.s.rig.configure(max_per_repo="1", without='["story"]')
        w = self.s.rig.worker(self.s.ledger)
        take, _, _ = w.candidates()
        self.assertEqual([i["number"] for i, _ in take], [fix])

    def test_a_story_has_slots_of_its_own_on_this_machine(self):
        self.s.rig.configure()
        state = self.s.rig.worker(self.s.ledger).wc.state_dir
        coder = worker.RepoLock(state, "lib", 1)
        builder = worker.RepoLock(state, "lib", 1, "story")
        second = worker.RepoLock(state, "lib", 1, "story")
        self.addCleanup(coder.release)
        self.addCleanup(builder.release)
        self.assertTrue(coder.acquire())
        self.assertTrue(builder.acquire())
        self.assertFalse(second.acquire())
        self.assertEqual(builder.path.name, "lib.story.lock")
        self.assertEqual(coder.path.name, "lib.lock")

    def test_a_coder_running_here_does_not_hold_the_builder_back(self):
        self.s.rig.configure()
        held = worker.RepoLock(self.s.rig.worker(self.s.ledger).wc.state_dir, "lib")
        self.assertTrue(held.acquire())
        self.addCleanup(held.release)
        self.s.story()
        outcome = self.s.run("--no-pr", "--tick", "3", story=self.s.build())
        self.assertEqual(outcome.code, worker.HANDED_BACK, outcome.summary)

    def test_claim_kind(self):
        self.assertEqual(worker.claim_kind({"labels": ["repo:lib", "review"]}), "review")
        self.assertEqual(worker.claim_kind({"labels": story_labels(CHANGE)}), "story")
        self.assertEqual(worker.claim_kind({"labels": ["repo:lib"]}), "other")


SESSIONS = Path(__file__).resolve().parent / "fixtures" / "sessions"


class TheCost(unittest.TestCase):
    def setUp(self):
        self.s = StoryRig(self)

    def cost(self, number: int) -> str:
        said = "\n".join(c["text"] for c in self.s.ledger.human_comments(number))
        (line,) = [x for x in said.splitlines() if x.startswith("Cost: ")]
        return line

    def test_the_hand_back_names_duration_turns_tokens_and_the_clis_cost(self):
        n = self.s.story()
        emit = str(SESSIONS / "claude-stream.jsonl")
        outcome = self.s.run("--no-pr", "--tick", "3", "--emit", emit, story=self.s.build())
        self.assertEqual(outcome.code, worker.HANDED_BACK, outcome.summary)
        line = self.cost(n)
        self.assertRegex(line, r"^Cost: duration \d+m\d\ds; turns 3; ")
        self.assertIn(
            "tokens 12000 (input 300, cached input 9000, cache creation 2000, output 700)", line
        )
        self.assertIn("total_cost_usd 0.50 (the CLI's own figure)", line)

    def test_a_stalled_run_reports_the_usage_it_had_so_far(self):
        n = self.s.story()
        emit = str(SESSIONS / "claude-stream-stopped.jsonl")
        outcome = self.s.run(
            "--no-pr", "--emit", emit, "--hang", story='check = "1s"\nstall = "2s"'
        )
        self.assertEqual(outcome.code, worker.NOT_HANDED_BACK, outcome.summary)
        line = self.cost(n)
        self.assertIn("turns 2", line)
        self.assertIn(
            "tokens 10110 (input 30, cached input 9000, cache creation 1000, output 80)", line
        )
        self.assertIn("so far: the agent was stopped", line)
        self.assertIn("total_cost_usd not reported", line)

    def test_an_agent_that_writes_no_json_still_says_its_duration(self):
        n = self.s.story()
        self.s.run("--no-pr", "--tick", "3", story=self.s.build())
        line = self.cost(n)
        self.assertRegex(line, r"^Cost: duration \d+m\d\ds; turns unknown; tokens unknown; ")
        self.assertIn("total_cost_usd not reported", line)

    def test_a_plain_items_hand_back_has_no_cost_line(self):
        n = self.s.ledger.file("Small", ["worker:w1", "repo:lib"])
        self.s.run("--emit", str(SESSIONS / "claude-stream.jsonl"))
        said = "\n".join(c["text"] for c in self.s.ledger.human_comments(n))
        self.assertNotIn("Cost:", said)


if __name__ == "__main__":
    unittest.main()
