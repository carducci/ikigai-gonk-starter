## Design resource-first

Before you design or brief a new app, module, endpoint family or feature, do the resource-first
pass: names first, code last. Write the result under `## Resource map` in the change's
`proposal.md`, or in the pull request when there is no spec. This repository's class is in
ikigraph's `artifacts/team/design-classes.toml`, and it sets the form:

- `roc` and `dogfood`: a map, a table with the columns set, name, kind and how, then the
  corridors and sealed names, and one line for each piece of code saying why it can't be a
  composition. The method and a worked example are in `docs/resource-design.md`.
- `legacy`: no map. For each new domain concept or endpoint family, one line,
  `Seam: <concept> would be` and the resource name in backticks.
- A fix or maintenance, in any class: `Not needed:` and the reason.
- A repository with no class (the starter fork, `carducci/ikigai-gonk-starter`): the pass is
  optional, as upstream's starter has it.

A design that hits a wall in the kernel is a finding. Say so in your report rather than coding
around it.
