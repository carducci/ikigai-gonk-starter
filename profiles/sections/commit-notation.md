## Commit in Arlo's Commit Notation

Every commit's first line starts `<risk> <intention> `, then the summary, e.g.
`^ F Refuse a thread key with a space (ledger item 412)`
(https://github.com/RefactoringCombos/ArlosCommitNotation). Reviewers' commits on a `review/`
branch too.

- Risk, from what you actually verified: `.` proven safe (a tool or scripted refactoring, or
  tests, docs or tooling only), `^` validated (tests ran green; for `F` or `B`, also 8 changed
  lines or fewer, tests included), `!` risky (a known risk you didn't check), `@` broken (a
  savepoint that may not build). No test run, no `^`.
- Intention, exactly one per commit. Uppercase changes one behaviour, lowercase changes none:
  `F` feature, `B` bugfix, `r` refactoring, `d` documentation, `e` environment and tooling,
  `t` tests only, `s` spec. Never `@ @`.
- Microcommits: one intention per commit, as small as builds and passes. Split an `F` or `B` over
  8 lines rather than marking it `!`.
