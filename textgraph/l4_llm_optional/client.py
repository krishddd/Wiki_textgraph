"""OpenAI-compatible chat client for the optional L4 pass (Phase 6).

A dependency-free client (stdlib ``urllib``) that speaks the ``/chat/completions``
API, so it works against OpenAI, a local vLLM/Ollama server, or any compatible
endpoint by pointing ``base_url`` at it. The **API key is read from the environment
only** (`TEXTGRAPH_LLM_API_KEY` / `API_KEY` / `OPENAI_API_KEY`) — it is never stored on
:class:`Config`, never hashed into ``config_hash``, and never written to an artifact
(G2, secret hygiene). If no key/endpoint is configured, :func:`resolve_client` returns
``None`` and L4 is skipped rather than failing the build.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from textgraph.core.config import Config

_API_KEY_ENV = ("TEXTGRAPH_LLM_API_KEY", "API_KEY", "OPENAI_API_KEY")
_BASE_URL_ENV = ("TEXTGRAPH_LLM_BASE_URL", "MODEL_BASE_URL", "OPENAI_BASE_URL")
_MODEL_ENV = ("TEXTGRAPH_LLM_MODEL", "MODEL_NAME", "OPENAI_MODEL")


def _first_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


class LLMError(RuntimeError):
    """Raised when the LLM endpoint is unreachable or returns an error."""


@dataclass(frozen=True)
class LLMClient:
    """Minimal OpenAI-compatible chat client. ``api_key`` comes from the environment."""

    base_url: str
    model: str
    api_key: str
    max_tokens: int = 256
    temperature: float = 0.0
    timeout: float = 60.0

    def complete(self, system: str, user: str) -> str:
        """Return the assistant message for a (system, user) prompt (deterministic-leaning)."""
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "stream": False,
            }
        ).encode("utf-8")
        url = self.base_url.rstrip("/") + "/chat/completions"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM request to {url} failed: {exc}") from exc
        try:
            content: str = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected LLM response shape: {body!r}") from exc
        return content.strip()


def resolve_client(config: Config) -> LLMClient | None:
    """Build an :class:`LLMClient` from config + environment, or ``None`` to skip L4.

    Precedence: explicit ``Config`` values win, else the environment. The API key is
    environment-only. Returns ``None`` (skip, don't fail) when key/base-url/model are
    incomplete, so a build with ``--llm`` degrades gracefully in an unconfigured env.
    """
    api_key = _first_env(_API_KEY_ENV)
    base_url = config.llm_base_url or _first_env(_BASE_URL_ENV)
    model = config.llm_model or _first_env(_MODEL_ENV)
    if not (api_key and base_url and model):
        return None
    return LLMClient(
        base_url=base_url,
        model=model,
        api_key=api_key,
        max_tokens=config.llm_max_tokens,
        temperature=config.llm_temperature,
    )
