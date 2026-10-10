# .gonk/queries/

Saved SPARQL over the ledger and the spec graph, one query per `<name>.rq` file: the
questions this team asks again (*which requirement has the most open work*, *which open
item is about a requirement a change removed*).

**Where they are going.** A saved query is a script whose language is `sparql`, and gonk can
hold it as a resource, `urn:script:{name}` from
[ikigai-script](https://github.com/ikigai-rs/ikigai-script): versioned by content, run with
`source urn:script:{name}:result` under the runner's own authority, and listed for an agent
in its tool manifold. A draft can come from a sentence: `urn:nl:sparql` from
[ikigai-nl](https://github.com/ikigai-rs/ikigai-nl) grounds a model in what the caller may
read, drafts and checks a query, and saves it as a DRAFT script for a person to publish.

gonk does not serve either family yet. `python3 tools/gonk.py init` asks, and says which it
finds. Until then the queries live here as files, and nothing in this repository publishes
them.

Empty in a new repository.
