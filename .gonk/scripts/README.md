# .gonk/scripts/

Workflow scripts: the steps this team runs over the ledger and the specs (sync a change's
tasks into items, a weekly report), one file each.

**Where they are going.** Like a saved query, a script is meant to be a resource on gonk,
`urn:script:{name}` from [ikigai-script](https://github.com/ikigai-rs/ikigai-script): a plan
or Lisp, published once, run with `sink urn:script:{name}:runs` for its effects, with every
run recorded (who, which version, under what authority), and never with more authority than
its publisher held. `urn:nl:script` in [ikigai-nl](https://github.com/ikigai-rs/ikigai-nl)
is the planned drafter for these; `urn:nl:sparql` drafts queries today.

gonk does not serve ikigai-script yet. `python3 tools/gonk.py init` asks, and says so.
Until it does, scripts live here as files, and nothing in this repository publishes them.

Empty in a new repository.
