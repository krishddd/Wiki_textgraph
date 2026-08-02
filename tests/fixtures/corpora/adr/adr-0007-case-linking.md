# ADR-0007: Link cases by shared beneficial owner

## Status
Accepted

## Context
Investigators MUST be able to see when two cases share a controlling person.

## Decision
WHY: We link Case nodes through a shared Beneficial Owner entity so an analyst can
traverse from one suspicious transaction to related cases in a single hop.

DECISION: Beneficial-owner resolution SHALL be reversible and never destructive.

## Consequences
Analysts can now ask why two cases are related and get a cited path.
