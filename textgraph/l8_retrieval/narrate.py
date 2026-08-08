"""Optional LLM answer synthesis (output) — grounded, cited, GENERATED.

TextGraph's default answers are templated and deterministic. This adds an *opt-in* layer
that composes a fluent natural-language answer — but only from the **retrieved, cited
evidence**, never the raw corpus. The model is instructed to cite each claim to a numbered
source and to abstain when the evidence doesn't support an answer. The result is tagged
``GENERATED`` and always shown next to its citations, so model prose can never masquerade
as an extracted fact (G2/G4). No endpoint configured ⇒ synthesis is simply skipped.
"""

from __future__ import annotations

from dataclasses import dataclass

from textgraph.l4_llm_optional.client import LLMClient, LLMError
from textgraph.l8_retrieval.model import Citation

_SYSTEM = (
    "You are a careful analyst. Answer ONLY from the numbered sources provided. "
    "Cite every claim inline as [n] using the source numbers. "
    "If the sources do not contain the answer, reply exactly: "
    "'The retrieved evidence does not answer that.' Be concise and factual."
)


@dataclass(frozen=True)
class NarratedAnswer:
    """An LLM-composed answer plus the cited evidence it was grounded on (GENERATED)."""

    text: str
    citations: list[Citation]
    tag: str = "GENERATED"

    def to_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "tag": self.tag,
            "citations": [c.to_dict() for c in self.citations],
        }


def narrate(
    client: LLMClient,
    question: str,
    passages: list[tuple[str, list[Citation]]],
) -> NarratedAnswer | None:
    """Compose a grounded, cited answer from ``passages`` (snippet, citations).

    Returns ``None`` when there is nothing to ground on. The model sees only the numbered
    snippets; the returned citations are the union of the sources handed to it, so every
    answer stays traceable to re-verifiable spans.
    """
    passages = [(s, c) for s, c in passages if s.strip()]
    if not passages:
        return None
    numbered = "\n".join(f"[{i + 1}] {snippet}" for i, (snippet, _) in enumerate(passages))
    user = f"Question: {question}\n\nSources:\n{numbered}\n\nAnswer (cite sources as [n]):"
    try:
        text = client.complete(_SYSTEM, user).strip()
    except LLMError:
        return None
    citations = [c for _, cites in passages for c in cites]
    return NarratedAnswer(text=text, citations=citations)
