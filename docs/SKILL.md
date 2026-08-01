# TextGraph Skill

> Short, instructional guide for an agent deciding when and how to use TextGraph.
> (Tool surface fills in through Phase 4; this file grows with it.)

## When to invoke

Use TextGraph when a question needs **structured, cited knowledge** drawn from a
body of text — not a one-shot summary. Good fits:

- multi-hop questions ("what connects A to C?")
- "why" / rationale questions (decisions, ADRs, contract recitals)
- "what changed / when" questions (bi-temporal history)
- contradiction detection across sources
- entity-centric lookups that must resolve aliases ("Acme", "ACME", "the company")

If you only need a quick paraphrase of one passage, plain retrieval is cheaper.

## Reading confidence tags

Every edge carries one of four tags. Trust them in this order:

| Tag | Meaning | Trust |
| --- | --- | --- |
| `STRUCTURAL` | from the document's own structure (zero models) | highest |
| `EXTRACTED` | encoder IE with a re-verifiable source span | high |
| `INFERRED` | derived across multiple pieces of evidence | medium |
| `GENERATED` | produced by the opt-in LLM pass | lowest — verify the span |

Filter by tag when you need certainty; every non-`GENERATED` edge has a byte-range
citation you can re-verify.

## Which tool for which question (available Phase 4+)

| Question shape | Tool |
| --- | --- |
| "find things about X" | `search` |
| "what's directly connected to X" | `neighbors` |
| "how are A and B related" | `path` |
| "why is X true" | `why` |
| "how did X change over time" | `timeline` |
| "where do sources disagree" | `contradictions` |
| "what are the main themes" | `communities` |
| "give me corpus stats" | `stats` |

Never ask TextGraph for raw Cypher/GQL — the tools return bounded, ranked,
citation-bearing context sized for a token budget (G6).
