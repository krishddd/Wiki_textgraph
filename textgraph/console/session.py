"""Multi-turn memory for the console Ask dock.

The Ask dock used to be stateless: every question was resolved on its own, so a natural
follow-up ("who else is connected to them?") lost the subject and fell back to a generic
answer. This module keeps a small, bounded, per-session history — what was asked, which
tool ran, which entity was in focus, which nodes came back — and uses it to resolve
**anaphora** (them / it / that / "who else") against the previous turn.

Design notes:

* **Pure and deterministic.** Resolution is rule-based string work over the session, never
  a model call, so the zero-LLM default keeps working and the behaviour is testable.
* **Server-side, bounded.** Sessions live in a small LRU (``SessionStore``); a rebuild
  clears them, and neither the graph nor any artifact is touched.
* **Never invents a subject.** If nothing was remembered, resolution returns the question
  unchanged and the normal routing runs — a follow-up simply behaves as it did before.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

# Words that stand in for a previously named entity. Deliberately conservative: only
# unambiguous third-person references, so we never hijack a question that names its own
# subject ("who controls that company" still resolves "that company" normally).
_PRONOUNS = frozenset(
    {
        "them",
        "they",
        "their",
        "theirs",
        "it",
        "its",
        "he",
        "him",
        "his",
        "she",
        "her",
        "hers",
        "this",
        "that",
        "those",
        "these",
    }
)
# "who else", "any others", "show more" — an explicit request for *further* neighbours of
# whatever is already in focus.
_ELSE_CUES = ("else", "other", "others", "another", "more")
_WORD = re.compile(r"[A-Za-z']+")


@dataclass
class Turn:
    """One question and what it resolved to."""

    question: str
    tool: str
    focus: str | None = None
    nodes: tuple[str, ...] = ()
    answer: str = ""
    citations: tuple[str, ...] = ()


@dataclass
class ChatSession:
    """A bounded conversation history for one Ask dock."""

    turns: list[Turn] = field(default_factory=list)
    max_turns: int = 20

    def remember(self, turn: Turn) -> None:
        """Append a turn, trimming the oldest beyond ``max_turns`` (G7: bounded memory)."""
        self.turns.append(turn)
        if len(self.turns) > self.max_turns:
            del self.turns[: len(self.turns) - self.max_turns]

    @property
    def last_focus(self) -> str | None:
        """The most recent entity the conversation was about."""
        for turn in reversed(self.turns):
            if turn.focus:
                return turn.focus
        return None

    def recent_nodes(self, limit: int = 40) -> list[str]:
        """Entity ids seen recently, most recent first, de-duplicated."""
        out: list[str] = []
        seen: set[str] = set()
        for turn in reversed(self.turns):
            for nid in turn.nodes:
                if nid not in seen:
                    seen.add(nid)
                    out.append(nid)
                    if len(out) >= limit:
                        return out
        return out


@dataclass
class FollowUp:
    """The result of resolving a question against the session."""

    question: str
    focus: str | None = None
    tool: str | None = None  # a forced tool, when the phrasing implies one
    resolved: str | None = None  # the entity name substituted in, for the UI to show


def _is_anaphoric(question: str) -> bool:
    """True when the question leans on a previously named subject."""
    words = [w.lower() for w in _WORD.findall(question)]
    return any(w in _PRONOUNS for w in words)


def _wants_more(question: str) -> bool:
    words = [w.lower() for w in _WORD.findall(question)]
    return any(w in _ELSE_CUES for w in words)


def resolve_followup(
    question: str,
    session: ChatSession | None,
    *,
    name_of: Callable[[str], str],
) -> FollowUp:
    """Resolve a follow-up question against ``session``.

    Substitutes a pronoun with the remembered entity's name so the normal entity resolver
    can find it, and — for "who **else** is connected to them?" — forces the ``neighbors``
    tool, since that phrasing is a one-hop expansion of the current focus rather than the
    two-entity path the wording would otherwise route to.

    Returns the question unchanged when there is nothing to resolve against.
    """
    focus = session.last_focus if session else None
    if not focus or not _is_anaphoric(question):
        return FollowUp(question=question, focus=focus)

    name = name_of(focus)
    if not name:
        return FollowUp(question=question, focus=focus)

    # Replace only whole-word pronouns, preserving the rest of the phrasing.
    def _sub(m: re.Match[str]) -> str:
        return name if m.group(0).lower() in _PRONOUNS else m.group(0)

    rewritten = _WORD.sub(_sub, question)
    tool = "neighbors" if _wants_more(question) else None
    return FollowUp(question=rewritten, focus=focus, tool=tool, resolved=name)


class SessionStore:
    """A small LRU of live Ask-dock sessions, keyed by a client-supplied id."""

    def __init__(self, max_sessions: int = 64) -> None:
        self._sessions: OrderedDict[str, ChatSession] = OrderedDict()
        self.max_sessions = max_sessions

    def get(self, session_id: str | None) -> ChatSession | None:
        """Fetch (or start) the session for ``session_id``; ``None`` when unkeyed."""
        if not session_id:
            return None
        existing = self._sessions.get(session_id)
        if existing is not None:
            self._sessions.move_to_end(session_id)
            return existing
        created = ChatSession()
        self._sessions[session_id] = created
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)
        return created

    def clear(self) -> None:
        """Drop every session — called when the graph is rebuilt under the console."""
        self._sessions.clear()
