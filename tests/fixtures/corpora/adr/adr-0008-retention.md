# ADR-0008: Evidence retention policy

## Status
Accepted

## Context
Regulators REQUIRED that source evidence be retained and re-verifiable.

## Decision
WHY: Every extracted claim MUST carry a byte-range citation so an auditor can
re-hash the exact source span. Evidence MUST NOT be deleted on contradiction; it is
invalidated instead.
