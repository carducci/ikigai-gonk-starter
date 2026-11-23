# Design: story items

## Context
`tools/worker.py` runs one item per process: claim, a fresh worktree, the agent under a preamble,
the hand-back. It already has a second mode, the review job, chosen by the item's ledger class and
finished by `Worker.finish_review`. A story is the third shape of run: long (hours, not minutes),
resumable, and checked by the worker before it is handed back as done.

## Decisions

### A story is told by its labels, not by a ledger class
A review job is a `ledger:ReviewJob`, a class the ledger defines. A story is marked by the label
`story` and one `change:<id>`. Labels are what a dispatcher already sets with `gonk.py dispatch`,
and the dispatch pins them (a label added after the dispatch routes nothing), so no ledger release
is needed and a small-items loop keeps stories out with `without = ["story"]`. The kind is decided
per item in `brief()` and `work_claimed`, never by loop configuration, so one loop can take both.
A ledger class can replace the label later without changing the run.

### The branch is the story's, so a later run resumes
The worktree's branch is `story/<id>`, not the per-run `worker/item-N-<stamp>`. When origin has
that branch the worktree starts from it; otherwise from `origin/<base>`. The item's own kept
worktrees are removed first (after a best-effort, never-forced push of their HEAD), because
`git worktree add -B` refuses a branch checked out in another worktree. Keeping the branch name
stable also lets the existing pull-request lookup by branch find the draft pull request again.

### Checkpoints push, and never force
Once a minute the worker reads HEAD and the number of ticked boxes in the change's `tasks.md`.
When either moved, it runs `git push origin HEAD:story/<id>`, never with `--force`: a push that is
refused (someone else pushed, history was rewritten) is logged and the run goes on, so the worker
can never destroy work on the branch. The first checkpoint opens one draft pull request against the
repository's base, unless one is open for the branch already. The agent is told never to mark it
ready and never to merge.

### Stalled is an ending of its own
No movement of HEAD or the ticked count for `[story] stall` (default 30m) stops the agent like an
overrun does, but the ending is named `stalled`, so the hand-back says the agent was stuck rather
than out of time. The overall budget is the loop's existing `budget`.

### The worker checks, and only a passing story is done
After any ending the worker pushes a last checkpoint and runs the checks itself: `openspec validate
<id> --strict`, no `- [ ]` left in `tasks.md`, the configured build command's
`AGENT-BUILD-RESULT {json}` line saying `"status":"pass"`, and a screenshot in the evidence directory
when the change touched a configured UI path. Each is one `- <check>: pass|FAIL <detail>` line. Only
when all pass (and the agent ended by itself) is the pull request marked ready and the story handed
back with evidence; otherwise the pull request stays a draft and the item is released with the
lines, so nothing reaches Michael as done unless the checks pass. A build that is not configured is
reported as `not configured` and does not pass.

### Cost is text on the hand-back, read from the agent's own output
The story's hand-back carries one line with the wall-clock duration, turns, tokens and the CLI's
own reported `total_cost_usd`, read straight from the agent's log: the `result` event of Claude
Code's `--output-format json` or `stream-json`. Nothing is sent anywhere else: it is text on the
hand-back, not a record. Because a stopped agent writes no result event, the per-message usage of a
`stream-json` log's `assistant` events is summed instead, so a stalled or overrun story still
reports what it had used. An agent with neither says `unknown`.

### A story counts only against stories
`max_per_repo` bounds the items of one repository a checkout's loops run at once, counted within a
kind: a review counted only reviews, any other item the rest. A story is a third kind. Counted
against the coders, a builder with `max_per_repo = 1` would never start while a coder held an item
of the same repository; counted only against stories, it runs beside them, in its own worktree and
on its own branch. The ledger count (`repo_holder`) and the machine's slots (`RepoLock`, one lock
file per kind) both go by the kind.

## Risks
- A refused checkpoint push leaves the branch behind the worktree; the worktree is kept, and the
  next run of the item pushes its HEAD before removing it.
- The stall clock reads only HEAD and ticks: an agent that works for 30 minutes without a commit is
  stopped. The preamble tells it to commit small and often.
