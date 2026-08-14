"""Forward-chaining Datalog subset: rules over ``(predicate, subject, object)`` facts.

Facts are triples. A rule has a body (a conjunction of triple *patterns*) and a head (one
triple pattern); a pattern term is a **variable** (leading ``?``) or a **constant**. The
engine joins each rule's body against the current fact set, substitutes the resulting
bindings into the head, and adds any new facts — iterating to a fixpoint. Because the fact
set is finite and only grows, the fixpoint always terminates; recursion (transitive closure,
ancestry) is handled naturally.

Everything is deterministic (facts and rules processed in sorted/declared order) so a given
``(facts, rules)`` input yields byte-identical output. Each derived fact keeps a
:class:`Derivation` — the rule that fired and the exact body facts that supported it — so any
inference is fully explainable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

Fact = tuple[str, str, str]  # (predicate, subject, object)


@dataclass(frozen=True)
class Pattern:
    """A triple pattern; any term beginning with ``?`` is a variable, else a constant."""

    predicate: str
    subject: str
    object: str


@dataclass(frozen=True)
class Rule:
    """``head :- body[0], body[1], ...`` — derive the head when the whole body matches."""

    rule_id: str
    body: tuple[Pattern, ...]
    head: Pattern


@dataclass(frozen=True)
class Derivation:
    """Provenance for one derived fact: the rule that fired and the facts that supported it."""

    fact: Fact
    rule_id: str
    support: tuple[Fact, ...]


def _is_var(term: str) -> bool:
    return term.startswith("?")


def _match(pattern: Pattern, fact: Fact, binding: dict[str, str]) -> dict[str, str] | None:
    """Extend ``binding`` so ``pattern`` unifies with ``fact``; ``None`` if it can't."""
    if pattern.predicate != fact[0]:
        return None
    out = dict(binding)
    for term, value in ((pattern.subject, fact[1]), (pattern.object, fact[2])):
        if _is_var(term):
            if term in out and out[term] != value:
                return None
            out[term] = value
        elif term != value:
            return None
    return out


def _subst(pattern: Pattern, binding: dict[str, str]) -> Fact:
    subj = binding.get(pattern.subject, pattern.subject)
    obj = binding.get(pattern.object, pattern.object)
    return (pattern.predicate, subj, obj)


def forward_chain(
    facts: list[Fact] | set[Fact],
    rules: list[Rule],
    *,
    max_iterations: int = 50,
    max_facts: int = 100_000,
) -> tuple[list[Fact], dict[Fact, Derivation]]:
    """Run the rules to a fixpoint; return the derived facts + their derivations.

    ``max_iterations`` bounds recursion depth and ``max_facts`` bounds blow-up (G7); both are
    safety rails, not normally reached. Only *newly derived* facts appear in ``derivations``.
    """
    known: set[Fact] = set(facts)
    derivations: dict[Fact, Derivation] = {}
    for _ in range(max_iterations):
        by_pred: dict[str, list[Fact]] = {}  # index rebuilt each round for the joins
        for f in known:
            by_pred.setdefault(f[0], []).append(f)
        for lst in by_pred.values():
            lst.sort()
        fresh: list[Fact] = []
        for rule in rules:
            bindings: list[dict[str, str]] = [{}]
            for pat in rule.body:
                nxt: list[dict[str, str]] = []
                for b in bindings:
                    for fact in by_pred.get(pat.predicate, ()):
                        m = _match(pat, fact, b)
                        if m is not None:
                            nxt.append(m)
                bindings = nxt
                if not bindings:
                    break
            for b in bindings:
                head = _subst(rule.head, b)
                if _is_var(head[1]) or _is_var(head[2]):
                    continue  # unsafe rule: head variable not bound by the body — skip
                if head not in known and head not in derivations:
                    support = tuple(_subst(p, b) for p in rule.body)
                    derivations[head] = Derivation(head, rule.rule_id, support)
                    fresh.append(head)
        if not fresh:
            break
        known.update(fresh)
        if len(known) >= max_facts:
            break
    return sorted(derivations), derivations


_ATOM = re.compile(r"\s*([A-Za-z_][\w]*)\s*\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)\s*")


def _term(tok: str) -> str:
    """A token is a variable if it starts uppercase (Datalog convention), else a constant.

    Quoted tokens are always constants (quotes stripped), so an entity name that happens to
    start uppercase can still be written literally as ``"Acme Corp"``.
    """
    tok = tok.strip()
    if len(tok) >= 2 and tok[0] in "\"'" and tok[-1] == tok[0]:
        return tok[1:-1]
    return "?" + tok if tok[:1].isupper() else tok


def _atom(text: str) -> Pattern:
    m = _ATOM.fullmatch(text)
    if not m:
        raise ValueError(f"cannot parse atom: {text.strip()!r}")
    return Pattern(m.group(1), _term(m.group(2)), _term(m.group(3)))


def parse_rules(text: str) -> list[Rule]:
    """Parse newline/period-separated Datalog rules into :class:`Rule` objects.

    Grammar (binary predicates only): ``head(A, B) :- body1(A, C), body2(C, B).`` Uppercase
    terms are variables, lowercase/quoted terms are constants. A fact (no body) is allowed as
    ``head(a, b).`` Lines starting with ``#`` or ``//`` are comments.
    """
    rules: list[Rule] = []
    n = 0
    for raw in re.split(r"[.\n]", text):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        head_txt, _, body_txt = line.partition(":-")
        head = _atom(head_txt)
        body = tuple(_atom(a) for a in _split_atoms(body_txt)) if body_txt.strip() else ()
        n += 1
        rules.append(Rule(rule_id=f"r{n}", body=body, head=head))
    return rules


def _split_atoms(body: str) -> list[str]:
    """Split a rule body on the commas *between* atoms (not the commas inside ``p(x, y)``)."""
    atoms, depth, start = [], 0, 0
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            atoms.append(body[start:i])
            start = i + 1
    tail = body[start:]
    if tail.strip():
        atoms.append(tail)
    return atoms
