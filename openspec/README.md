# openspec/

What this system is supposed to do, written where the code is, in
[OpenSpec](https://github.com/Fission-AI/OpenSpec)'s layout (1.x). It is the default spec
format here; `.gonk/layout.toml` declares it as a `[[spec]]` entry, so another format can
sit beside it later with its own mapping.

```text
openspec/
├── config.yaml     OpenSpec's project file
├── specs/          what the system does NOW, one folder per capability: specs/<capability>/spec.md
└── changes/        what someone PROPOSES, one folder per change: proposal.md, specs/…, tasks.md
    └── archive/    finished changes, moved here intact by `openspec archive`
```

Both halves are empty in the starter; the library-lending sample fills them. Nothing here
needs OpenSpec's own CLI: the format is Markdown with fixed heading prefixes
(`### Requirement:`, `#### Scenario:`), and the
[gonk Book's spec part](https://ikigai-rs.github.io/ikigai-tutorial/gonk/spec/openspec.html)
teaches it, lifts it to a graph and turns a change's tasks into ledger items.
`python3 tools/gonk.py seed` does the last part without a graph: one item per open task,
keyed by the task's IRI, as the Book's sync does.

## Three conventions that are ours, not OpenSpec's

- **Artifacts.** A spec names the artifacts that implement it, and a change names the
  artifacts it touches, on one line that starts with `Artifacts:` and lists each name in
  backticks. In a spec it goes in `## Purpose`; in a change, in `proposal.md`'s `## Impact`:

  ```markdown
  ## Impact
  - Artifacts: `service`, `cli`
  ```

  Each name is a directory under `artifacts/`. `python3 tools/gonk.py init` refuses a name
  with no directory. OpenSpec reads the line as ordinary prose.
- **A task names its requirement.** A task that ends in a requirement's name in parentheses,
  `- [ ] 1.2 Return the turn (Players alternate)`, says which requirement it implements, so it
  can become a ledger item *about* that requirement (the gonk Book's convention).
- **A task names its model.** After its number a task may carry `[haiku]`, `[sonnet]` or
  `[opus]`, optionally with `repo:<name>`: `- [ ] 1.1 [sonnet repo:other] Do x`. `python3
  tools/gonk.py seed` files the item with `agent:claude-<model>` and `repo:<name>` (default: this
  repository, from its `origin`, else its folder) and leaves the hint out of the title. `seed`
  files nothing and names the line when an open task has an unknown model, an unknown or repeated
  word, a `repo:` name that isn't a repository name, no text after the hint, no title once the
  hint and citation are removed, or a hint on a `(human: …)` task (`human` in any case, space
  allowed before the colon). A bracket followed at once by `(` is a Markdown link, not a hint. A
  checked-off task is never refused; `seed --dry-run` shows each item's labels.
