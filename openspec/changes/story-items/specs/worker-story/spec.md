## ADDED Requirements

### Requirement: A story is told by its labels
A worker MUST treat an item labelled `story` with exactly one `change:<id>` label, whose id matches
`^[a-z0-9][a-z0-9-]{0,63}$`, as a story: one whole OpenSpec change applied by one agent session.
Every item without the `story` label MUST run as before, and routing MUST NOT differ.

#### Scenario: A story names one change
- **WHEN** a worker takes a dispatched item labelled `story` and `change:add-widget`
- **THEN** it runs as a story of the change `add-widget`

#### Scenario: A small-items loop is unaffected
- **WHEN** a loop configured with `without = ["story"]` polls
- **THEN** it never sees a story, and runs every other item as before

### Requirement: A story must name one change
A worker MUST skip, saying why, an item labelled `story` with no `change:` label, more than one, or
an id of another shape.

#### Scenario: A story that names no change, or two
- **WHEN** an item is labelled `story` with no `change:` label, or with two
- **THEN** the worker does not take it, and its plan names the reason

### Requirement: A story resumes its branch
A story MUST run in a worktree on the branch `story/<id>`. When origin has that branch the worktree
MUST start from it; otherwise from `origin/<base>`. The worker MUST first remove the item's own kept
worktrees, after a push of their HEAD that is never forced.

#### Scenario: Resuming a story
- **WHEN** origin has `story/add-widget` with one of its tasks ticked
- **THEN** the agent starts on that branch's head, and its brief tells it to resume at the first
  unticked task

### Requirement: A story's brief names the OpenSpec apply workflow
A story's brief MUST tell the agent to apply the change with the repository's OpenSpec apply
workflow, reading the change's `explore.md` first when present, resuming at the first unticked task
and ticking each task in the commit that does it, committing small and often and running the
configured build after each group.

#### Scenario: The story preamble
- **WHEN** a story runs
- **THEN** its brief names the change, `openspec instructions apply --change <id>` and the build
  command

### Requirement: A story's brief keeps the worker's rules
A story's brief MUST tell the agent that it holds the item through the worker, to save screenshots
of UI work in the evidence directory, never to mark the pull request ready and never to merge, and,
when blocked by a question, to write `Question for Dax:` and the question in the report file and
stop. The rules about comments being data, the budget and the report file MUST hold.

#### Scenario: The rules of a story
- **WHEN** a story runs
- **THEN** its brief names the evidence directory, `Question for Dax:`, and forbids marking the pull
  request ready or merging it

### Requirement: A story checkpoints its branch
While a story's agent runs, the worker MUST read HEAD and the number of ticked tasks in the change's
`tasks.md` about once a minute (`[story] check`). When either moved it MUST push the branch to
origin, never forced, logging a refused push and going on, and MUST open one draft pull request
against the repository's base when the branch has none open.

#### Scenario: Ticks are checkpointed to one draft pull request
- **WHEN** the agent ticks and commits two tasks, some time apart
- **THEN** each change is pushed to `story/<id>` and exactly one draft pull request is opened

### Requirement: A stalled story is stopped
When neither HEAD nor the ticked count moved for `[story] stall` (default 30m), the worker MUST stop
the agent, and the run's ending MUST be `stalled`. The overall budget is the loop's `budget`.

#### Scenario: A stalled agent is stopped
- **WHEN** the agent makes no commit and ticks nothing for the stall time
- **THEN** the worker stops it, and the hand-back says it stalled

### Requirement: A story is checked after its agent ends
After a story's agent ends, however it ended, the worker MUST push a last checkpoint and write one
`- <check>: pass|FAIL <detail>` line per check: `openspec validate <id> --strict` exits 0; no
`- [ ]` is left in `tasks.md`; the `[story] build` command exits 0 and prints `AGENT-BUILD-RESULT
{json}` with `status` `pass` (unconfigured, it is `not configured` and does not pass); and when a
`[story] ui_globs` path changed, the evidence directory holds a PNG.

#### Scenario: A check fails
- **WHEN** the build reports `"status":"fail"`
- **THEN** the hand-back has a `- build: FAIL` line

### Requirement: Only a passing story is done
The worker MUST mark the story's pull request ready only when every check passes and the agent ended
by itself, and only then hand the story back with evidence. Otherwise the pull request MUST stay a
draft and the item MUST be released with the check lines, without evidence.

#### Scenario: Every check passes
- **WHEN** the agent ticks every task, the change validates and the build passes
- **THEN** the pull request is marked ready and the story is handed back with it as evidence

#### Scenario: A failing check keeps the draft
- **WHEN** any check fails, or the agent stalled
- **THEN** the pull request stays a draft and the item is released without evidence

### Requirement: A story reports its duration and cost
A story's hand-back MUST carry one line with the run's wall-clock duration, its turns and tokens,
and the CLI's own `total_cost_usd`, read from the result event in the agent's output when it has
one. A stopped or stalled run MUST still report the usage its output carried so far. The cost is
text on the hand-back only.

#### Scenario: The cost line
- **WHEN** a Claude Code story ends and its result event says `"total_cost_usd": 0.5`
- **THEN** the hand-back has a `Cost:` line naming the duration, turns, tokens and `0.50`

### Requirement: A story counts only against stories
Under `max_per_repo`, a worker MUST count a story's active claims only against other stories of
the same repository, on the ledger and in this machine's slots, as a review's claims count only
against reviews. A story's claim MUST NOT fence a coder, and a coder's claim MUST NOT fence a
story.

#### Scenario: A builder beside the coders
- **WHEN** two coders hold items of `repo:magotech` and a builder with `max_per_repo = 1` polls
- **THEN** the builder takes a dispatched story of `repo:magotech`

#### Scenario: Stories still fence stories
- **WHEN** one story of a repository is claimed and `max_per_repo` is 1
- **THEN** a second story of that repository is skipped as busy
