# Security Policy

## Reporting

Report suspected vulnerabilities privately via GitHub Security Advisories on
[krishddd/Wiki_textgraph](https://github.com/krishddd/Wiki_textgraph/security).
Please do not open a public issue for undisclosed vulnerabilities.

## Threat model (built in, not bolted on)

TextGraph treats **all corpus content as untrusted data**. This is a design
invariant enforced from Phase 1 onward and re-verified in Phase 10:

- **Prompt injection via corpus content.** Corpus text is never interpolated into
  a system-level position in any prompt. When the opt-in LLM pass (L4) runs, corpus
  text is passed as clearly delimited data, and any resulting edge that cannot be
  grounded in a source span is discarded.
- **Provenance integrity.** Every non-`GENERATED` edge carries a re-verifiable
  byte-range citation (G3). Tampered or stale citations are detectable by re-hash.
- **Local-first by default (G2).** No network calls unless explicitly enabled; text
  never leaves the machine by default.
- **Tenant safety (G8, Phase 9).** Authorization is checked *inside* traversal and
  PPR, not as a post-filter — unauthorized nodes get zero transition probability.

## Supported versions

Pre-1.0: only the latest tagged release is supported. A support matrix is added at
v1.0.
