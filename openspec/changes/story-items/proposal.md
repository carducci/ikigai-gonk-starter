# Story items: one whole OpenSpec change, applied by one builder session

## Why
Michael decided on 2026-11-22, "Drain, then one lane at a time": one item per process instance,
and a story applied whole. A story is one OpenSpec change, a potentially shippable increment, and
until now a worker could only take small items that each fit a 45-minute budget and one pull
request. Splitting a change into one item per task loses the thread between tasks, restarts work
that a stopped run had half done, and leaves nobody checking the whole change mechanically before
it reaches Michael as done.

## What Changes
- A second item kind in `tools/worker.py`: an item labelled `story` with exactly one
  `change:<id>` label is a story. A story with no `change:` label, several, or a malformed id is
  skipped, saying why.
- A story runs on the branch `story/<id>`, resumed from origin when that branch exists, under a
  story preamble that tells the agent to apply the change with the repository's OpenSpec apply
  workflow, tick each task in `tasks.md` in the commit that does it, and never mark the pull
  request ready or merge it.
- While the agent runs, the worker checkpoints about once a minute: when HEAD or the count of
  ticked tasks moves it pushes the branch (never forced) and opens one draft pull request; when
  nothing moves for `[story] stall` (default 30m) it stops the agent as stalled.
- After the agent ends, however it ended, the worker checks the change: `openspec validate --strict`,
  every task ticked, the configured build reporting `AGENT-BUILD-RESULT {"status":"pass"}`, and
  screenshots when UI paths changed. It hands the story back as done only when every check
  passes, with its pull request still a draft: the router reviews it and marks it ready.
- The hand-back says the run's duration, turns, tokens and the CLI's own reported cost, as text,
  including for a run that was stopped.
- An optional `[story]` table in the worker configuration: `stall`, `check`, `build`, `ui_globs`,
  `evidence`.
- Under `max_per_repo`, a story's claim counts only against other stories, as a review's counts
  only against reviews, so a builder with `max_per_repo = 1` runs beside the coders of the same
  repository instead of waiting until none of them holds an item.

## Impact
Artifacts: none

Touches `tools/worker.py` (the duration, turns, tokens and cost are read straight from the
agent's stream-json result event in its log), `worker/README.md`, the workers profile's rules and
harness, and the worker tests and fakes. A small-items loop is unaffected except that it adds
`story` to its `without`.
