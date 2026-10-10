# ikigai-gonk-starter

**Work with gonk the way ikigai does: specs in the repository, the work in a ledger, a
claim before every change, and any agent.** This is the empty starting point for a
repository whose work is tracked by [gonk](https://github.com/ikigai-rs/ikigai-gonk), the
ledger and review host the ikigai project builds itself with. Use it as a template, run one
command, and Claude Code, Codex, pi, Hermes and the people on the team all work by the same
short set of rules, against the same ledger, without stepping on each other.

It is for a team, or one person running several agents, who want three things an agent's
chat history does not give them: **what the software is supposed to do**, written down where
the code is; **what to do next**, as a ranked answer with reasons; and **who is doing what
right now**, as a claim that expires rather than a guess.

## The loop

```sh
python3 tools/gonk.py next                            # what is ready, ranked, and why
python3 tools/gonk.py claim 12                        # take it, on a 30-minute lease
# reproduce, fix, open a pull request, get CI green
python3 tools/gonk.py report 12 --evidence <PR URL>   # the evidence on the item; hand it back
python3 tools/gonk.py close 12 --evidence <PR URL>    # whoever dispatched it, once it holds
```

That is the whole protocol, and [`AGENTS.md`](AGENTS.md) states its rules: claim before you
write, one agent per item and per working tree, reproduce before you fix, every change
through a pull request with green CI, evidence on every report and close, and never a bare
`#N`. Every agent reads that one file.

## What is in it

```text
AGENTS.md                the rules, for every agent and every person
CLAUDE.md -> AGENTS.md   the same file, under the name Claude Code reads
openspec/                specs (what the system does now) and changes (what is proposed)
artifacts/<name>/        one directory per deployable thing, any language each
.gonk/                   which ledger, how to reach gonk, and where everything lives
  layout.toml            the spec format(s), the artifacts root, queries, scripts
  gonk.toml              the ledger this repository's work lives in
  queries/  scripts/     saved SPARQL and workflow scripts (reserved; see below)
tools/gonk.py            init, file, next, claim, release, report, close, status
hooks/claude/            an OPTIONAL Claude Code hook that refuses edits without a claim
```

Everything is empty until you fill it. `tools/gonk.py` is standard-library Python (3.11 or
later) with no dependencies; `just` recipes wrap it one-for-one for those who have `just`.

## Setting it up

You need gonk running somewhere, and `ikigai`, its command line, on every machine that
works in the repository:

```sh
cargo install --locked --git https://github.com/ikigai-rs/ikigai-gonk ikigai-gonk
cargo install --locked ikigai-cli --features quic
```

gonk's [fresh-machine runbook](https://github.com/ikigai-rs/ikigai-gonk/blob/main/docs/fresh-machine.md)
covers starting it. Then, in your copy of this repository, `init` writes what you tell it and
prints exactly what is still missing. It reads no environment variables; flags and the files
under `.gonk/` are the whole configuration, and a missing piece is an error that names the
command that supplies it.

### gonk on this machine

```sh
python3 tools/gonk.py init --ledger acme --socket ~/.ikigai/gonk.sock --holder claude-1
```

The ledger name goes into `.gonk/gonk.toml` (committed, so every clone works in the same
ledger); the socket and the holder go into `.gonk/local.toml` (git-ignored, because they are
this machine's and this working tree's). A ledger has no create step: it exists once
something is filed in it, and `init` says so. Over the socket every request is gonk's
owner's, so the log cannot tell your agents apart; that is fine on your own machine, and the
reason the remote setup is different.

### gonk on another machine

The remote door is **QUIC with a client certificate per machine**. Each machine makes its
own identity, so its private key never leaves it:

```sh
ikigai cert generate --dir ~/gonk-cert
python3 tools/gonk.py init --ledger acme --holder bug-worker \
    --quic quic://gonk-host:1060 --cert-dir ~/gonk-cert
```

`init` prints the machine's identity, `urn:iki:gonk:client:<fingerprint>` (the name gonk
puts on every request it makes, on every item it files, and in its access log), and the
lines gonk's operator adds for it: one `ikigai-gonk client add … --cert client.crt --ledger
acme=write` command, or the `clients.json` and `grants.json` entries by hand. The operator
restarts gonk and sends back the `server.crt` from the bundle `client add` wrote; copy it
over the one in `~/gonk-cert` (`cert generate` wrote a server identity of its own there,
which is not gonk's, so this machine could not pin gonk with it). Then `init` reports the
machine ready. This works the same for an unattended machine as for a person's laptop,
and a claim from it is stamped a **machine**'s by gonk, never the caller's choice.

**Why not HTTP for a remote machine?** gonk's HTTP door listens on loopback only and refuses
any other bind until it has TLS and a real domain for passkeys. A tunnel to that port would
reach it, but every write through it is `anon`, under the anonymous grant: no name per
machine, so neither claims nor items could be told apart, and the rule that keeps a writer
from naming someone else as an item's author cannot run. HTTP is the right door for a browser
and for `curl` on the gonk machine itself; QUIC is the door for other machines.

### One transport, and MCP for agents

Every request `tools/gonk.py` makes goes through `ikigai` with an **alias mount**:
`--mount urn:gk:=<socket>` or `--mount urn:gk:=quic://host:port --cert-dir <dir>`, and the
ledger's `urn:iki:ledger:acme:claim` is then `urn:gk:iki:ledger:acme:claim`. One client
for both doors means one code path to test, and the alias means no name the tool sends can
resolve against something bound in the local `ikigai` by accident. The `ikigai` client also
fetches each resource's contract from gonk before it sends, so arguments are routed by the
ledger's own declarations rather than by this script's guesses.

An agent that speaks MCP is configured with `ikigai mcp`, which `init` prints for your
transport, for example `ikigai mcp --override urn:iki:ledger:=quic://gonk-host:1060
--cert-dir ~/gonk-cert`. Its tools are the ledger's own actions (`ledger-next__source`,
`ledger-claim__sink`, …) filtered by the capability the session holds, so an agent is never
offered what it may not do. The [gonk Book's MCP chapter](https://ikigai-rs.github.io/ikigai-tutorial/gonk/agent/mcp.html)
walks through it, including the client-side `--grant` ceiling.

## Each agent, and the one instruction file

| agent | reads | what to do |
| --- | --- | --- |
| Claude Code | `CLAUDE.md` | nothing: it is a link to `AGENTS.md` |
| Codex | `AGENTS.md` | nothing: Codex reads `AGENTS.md` from the project root down to the working directory ([docs](https://developers.openai.com/codex/guides/agents-md)) |
| Hermes Agent | `AGENTS.md` | nothing, unless the project also has a `.hermes.md` or `HERMES.md`, which Hermes ranks first and reads INSTEAD ([docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files)) |
| pi | `AGENTS.md` or `CLAUDE.md` | nothing: pi loads context files from its agent directory, the working directory and its parents ([docs](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/configuration.md)) |

Checked against each project's documentation on 2026-10-10. Two things that documentation
does not say, so this does not claim them: whether pi reads BOTH `AGENTS.md` and `CLAUDE.md`
when one directory holds both (here they are one file, so at worst it reads the rules twice),
and whether pi or Hermes can be pointed at a differently named file. Codex can, with
`project_doc_fallback_filenames`, but has no need to here.

## The optional Claude Code hook

`hooks/claude/require-claim.py` turns the first rule into a refusal for Claude Code: a file
edit in this repository is refused unless this working tree holds a claim that gonk still
says is its own, with time left on the lease. It is a second layer, never the only one: the
protocol works without it, every other agent keeps the rules by reading them, and it cannot
see a file written by a shell command. To turn it on, merge
[`hooks/claude/settings.sample.json`](hooks/claude/settings.sample.json) into
`.claude/settings.json`. See [`hooks/claude/README.md`](hooks/claude/README.md).

## Queries and scripts

`.gonk/queries/` (saved SPARQL over the ledger and the spec graph) and `.gonk/scripts/`
(workflow scripts) are reserved, and `layout.toml` names them. They are meant to become
resources on gonk: a query or a script published as `urn:script:{name}` with
[ikigai-script](https://github.com/ikigai-rs/ikigai-script) (versioned by content, run under
the runner's own authority, every run recorded), and drafted from a sentence by
`urn:nl:sparql` from [ikigai-nl](https://github.com/ikigai-rs/ikigai-nl). gonk does not serve
either yet. `init` asks it and says which it finds, and until then these are plain files.

## Coming next

- **A generator and a sample app**: a library-lending system as two artifacts (a service and
  a command-line client) with its specs in OpenSpec, whose scenarios are a shared test-vector
  file every language's tests run. Python first. ([#1134](http://localhost:1060/l/default/item/1134))
- **More languages** for the generator: Deno, Rust and Go, each passing the same vectors.
  ([#1135](http://localhost:1060/l/default/item/1135))
- **A second spec format**, beside OpenSpec, lifted to the same graph and ledger items by a
  mapping file rather than code. ([#1136](http://localhost:1060/l/default/item/1136))
- **Remote dispatch: a gonk worker.** A loop on another machine that pulls `next`, claims an
  item with a lease, runs the configured agent, renews the lease while it works, reports with
  evidence and hands the item back, all over that machine's QUIC identity. Closing stays with
  the dispatcher. ([#1139](http://localhost:1060/l/default/item/1139), with the worker's
  narrower grant in [#1143](http://localhost:1060/l/default/item/1143))
- **The gonk Book's chapters** on a project of your own, walking the generated sample from
  a spec change to a closed item. ([#1137](http://localhost:1060/l/default/item/1137))

(The `#` links are items in ikigai's own ledger, on its gonk.)

## Developing this starter

```sh
python3 -m venv .venv && .venv/bin/pip install ruff==0.16.1
just gates          # or scripts/gates.sh: ruff check, ruff format --check, the tests
```

The tests are standard-library `unittest`. The integration tests start a scratch gonk of
their own (a temporary directory, an ephemeral port, its own socket) when `ikigai-gonk` and
`ikigai` are on PATH, and skip, saying why, when they are not, as in CI.

## License

Licensed under either of [Apache License, Version 2.0](LICENSE-APACHE) or
[MIT license](LICENSE-MIT) at your option.
