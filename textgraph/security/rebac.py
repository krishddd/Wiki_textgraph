"""Relationship-Based Access Control — a small deterministic Zanzibar/OpenFGA (Phase 9).

The gap analysis (§3.1) models enterprise authorization as *graph edges*: permissions are
derived from structural relations, so "a user gains access to a document via transitive
policy paths connecting user-group memberships to folder-ownership structures". This is a
pure-Python, dependency-free realisation of that idea — relation tuples
``(object, relation, subject)`` plus a bounded, deterministic reachability check — good
enough to enforce and to red-team. A real OpenFGA/Zanzibar deployment plugs in behind the
``[security]`` extra (see :mod:`textgraph.security.policy`); this default needs no service.

Supported relations and their rewrites (Zanzibar "userset rewrite" rules):

* ``owner`` / ``viewer`` — direct read grants. ``owner`` implies ``viewer``.
* ``member`` — group membership; nested groups (a group that is a member of a group) are
  followed transitively.
* ``parent`` — object hierarchy; ``viewer`` is inherited from an object's parent (a folder
  viewer can view the folder's documents), which is the transitive policy path above.

A subject is a ``user:<id>``, a ``group:<id>``, or a *userset* ``<object>#<relation>``
(everyone who has ``relation`` on ``object``). Iteration is sorted and depth-bounded, so
every check is deterministic and terminates on cyclic policies (G1/G7).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# Depth cap for policy-path traversal: deep enough for realistic folder/group nesting,
# bounded so a cyclic or adversarial policy can never loop (G7).
_MAX_DEPTH = 16
# Relations that, alone, grant read access to an object.
_READ = ("owner", "viewer")


@dataclass(frozen=True, order=True)
class RelationTuple:
    """A single authorization edge ``object#relation@subject`` (Zanzibar tuple)."""

    object: str  # e.g. "doc:d1", "folder:f1", "group:analysts"
    relation: str  # "owner" | "viewer" | "member" | "parent"
    subject: str  # "user:alice" | "group:eng" | userset "folder:f1#viewer" | parent obj


class RebacStore:
    """A deterministic relation-tuple store answering "can this subject read this object?"."""

    def __init__(self, tuples: Iterable[RelationTuple] = ()) -> None:
        self._tuples = sorted(set(tuples))
        # (object, relation) -> sorted subjects; and subject -> groups it is a member of.
        self._idx: dict[tuple[str, str], list[str]] = {}
        self._member_of: dict[str, list[str]] = {}
        for t in self._tuples:
            self._idx.setdefault((t.object, t.relation), []).append(t.subject)
            if t.relation == "member":
                self._member_of.setdefault(t.subject, []).append(t.object)
        for key in self._idx:
            self._idx[key].sort()
        for s in self._member_of:
            self._member_of[s] = sorted(set(self._member_of[s]))

    def _subjects_for(self, obj: str, relation: str) -> list[str]:
        return self._idx.get((obj, relation), [])

    def expand_subjects(self, seed: Iterable[str]) -> frozenset[str]:
        """Close a subject set under (possibly nested) group membership, deterministically."""
        seen = set(seed)
        frontier = sorted(seen)
        while frontier:
            s = frontier.pop()
            for grp in self._member_of.get(s, []):
                if grp not in seen:
                    seen.add(grp)
                    frontier.append(grp)
        return frozenset(seen)

    def check(self, subjects: Iterable[str], obj: str) -> bool:
        """True if any of ``subjects`` (user + groups) may read ``obj`` (transitively)."""
        return self._holds(obj, "viewer", self.expand_subjects(subjects), set(), _MAX_DEPTH)

    def _holds(
        self,
        obj: str,
        relation: str,
        subs: frozenset[str],
        visiting: set[tuple[str, str]],
        depth: int,
    ) -> bool:
        key = (obj, relation)
        if depth < 0 or key in visiting:
            return False
        visiting = visiting | {key}
        for subj in self._subjects_for(obj, relation):
            if subj in subs:
                return True
            if "#" in subj:  # userset "<object>#<relation>"
                o2, _, r2 = subj.partition("#")
                if self._holds(o2, r2, subs, visiting, depth - 1):
                    return True
        # Userset rewrites: owner => viewer, and viewer is inherited from the parent object.
        if relation == "viewer":
            if self._holds(obj, "owner", subs, visiting, depth - 1):
                return True
            for parent in self._subjects_for(obj, "parent"):
                if self._holds(parent, "viewer", subs, visiting, depth - 1):
                    return True
        return False
