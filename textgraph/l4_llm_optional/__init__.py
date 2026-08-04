"""L4 — optional LLM pass (Phase 6, opt-in, GENERATED-tagged).

Synthesizes model-authored community summaries and quarantines them by tag so they can
never be mistaken for extracted facts. Off by default (G2); OpenAI-compatible client
with the API key read from the environment only. See :mod:`textgraph.l4_llm_optional.synthesize`.
"""

from textgraph.l4_llm_optional.cache import PromptCache
from textgraph.l4_llm_optional.client import LLMClient, LLMError, resolve_client
from textgraph.l4_llm_optional.synthesize import synthesize

__all__ = ["LLMClient", "LLMError", "PromptCache", "resolve_client", "synthesize"]
