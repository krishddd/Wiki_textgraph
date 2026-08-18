# Collaborative mode — the design (shared state without losing local-first)

**The value:** several analysts working one case together — assign entities to each other, mark
things confirmed / disputed / pending, leave notes, and *see each other's work as it happens* —
instead of emailing screenshots.

**The tension:** real collaboration needs **shared, mutable, server-side state**. TextGraph's
default is local-first and its central artifact is *immutable and byte-identical*. A naive
"collaborative graph" would break the moat.

## The resolving idea (already seeded in v4.11)

Split the world in two:

- **`graph.json` — the immutable shared ground truth.** Never written by collaboration. It is the
  reproducible artifact everyone agrees on; determinism (G1) is untouched.
- **A collaboration sidecar — the mutable overlay.** All human judgment lives here: annotations,
  who-said-what, assignments, an activity log. It is explicitly non-deterministic (it has
  timestamps and authors) precisely *because* it is not part of the reproducible build.

v4.11's annotation sidecar already established this split for one analyst. Collaborative mode is
the sidecar grown up: **attribution, assignments, and live sync.**

## What changes

1. **Attribution.** Every annotation records its `author` and `updated` time. Identity is
   *declared* (`console --analyst "Dana"`), not authenticated — this is collaboration convenience,
   not a security boundary (that is what `--token` and the FGAC policy are for). Honest by design.
2. **Assignments.** An entity can be assigned to an analyst (`assignments[node] = "Dana"`), so a
   team can divide a case. A "assigned to me" filter and an assignee label on the node.
3. **Live sync — poll, not sockets.** The sidecar carries a monotonic `version`; the console polls
   `GET /api/collab` every few seconds and only re-fetches the overlay when the version changed.
   This keeps the dependency-free stdlib `http.server` model (no websockets) while still showing a
   colleague's change within seconds.
4. **Activity log.** A bounded list of "who did what, when" so the team can see recent movement.
5. **Multi-process safety.** Two console processes may point at the same sidecar file. Writes
   **reload-before-write under a lock** and merge, so concurrent editors don't clobber each other's
   *other* nodes (per-node last-write-wins is acceptable and expected).

## Why this stays honest

- **`graph.json` is byte-identical** with or without collaboration — the determinism gate is
  untouched. The sidecar is a separate file the build never reads.
- **No new dependency, no websockets** — the stdlib server + version-polling is enough for a case
  team, and keeps the "runs on a laptop, offline" promise.
- **Backward compatible** — a v4.11 flat `annotations.json` loads unchanged; new fields default in.
- **Not a security claim** — declared identity is for attribution. Access control remains `--token`
  / the ReBAC-ABAC policy. The docs say so plainly.

## Plan (release 5.0.0 — the collaborative milestone)

| # | change |
|---|--------|
| 1 | Grow `AnnotationStore` → a collaboration store: annotations gain `author`/`updated`; add `assignments`, a monotonic `version`, and a bounded `activity` log. Reload-before-write under a lock. Back-compat load. |
| 2 | Server: `--analyst NAME`; `/api/annotate` stamps author; new `POST /api/assign`; new `GET /api/collab` (full overlay + version + current analyst). |
| 3 | Console: poll `/api/collab`, refresh overlay + redraw on version change; assignment control + assignee label; "last edited by …"; an **activity** panel; "assigned to me" filter; analyst name in the header. |
| 4 | Tests: attribution, assignments, version monotonicity, reload-before-write merge, back-compat load, collab payload; browser-verify two-client sync. |
| 5 | Verify end-to-end on the real `C:\Users\hp\Downloads\case` corpus + `case-out` build. |

5.0.0 is a **milestone** bump (roadmap of bigger bets complete: roles, federation, Jupyter,
collaboration), not a breaking change — the API and `graph.json` format are unchanged.
