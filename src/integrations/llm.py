"""Shared Anthropic LLM client.

Per the coding standards (file ``04``, rule 3.4), every external LLM call goes
through this one wrapper — no module imports ``anthropic`` directly — and this
is the only place the timeout and exponential-backoff retry policy is applied.

It lives in the ``integrations`` layer (not inside a single feature module)
because more than one module now needs it: ``sample_data`` generates sample
queries and ``email_draft`` drafts emails. Shared infrastructure belongs here
so feature modules stay independent of one another.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam

from src.config import Settings, get_settings
from src.observability import get_logger

logger = get_logger(__name__)


class LLMGenerationError(Exception):
    """Raised when the LLM call fails after exhausting all retry attempts."""


class LLMClient:
    """Generates text completions via the Anthropic Messages API.

    Args:
        settings: Application settings supplying the API key, model id,
            timeout, and retry budget.
    """

    def __init__(self, settings: Settings) -> None:
        """Construct the underlying Anthropic client from settings."""
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.llm_timeout_seconds,
        )
        self._model = settings.llm_model
        self._max_retries = settings.llm_max_retries

    def generate(self, *, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        """Request a single completion from a plain-text prompt.

        A thin wrapper over :meth:`generate_multimodal` for the common
        text-only case (used by ``sample_data`` and ``email_draft``).

        Args:
            system_prompt: The system instructions for the request.
            user_prompt: The user-turn content.
            max_tokens: Maximum tokens to generate.

        Returns:
            The concatenated text of the model's response.

        Raises:
            LLMGenerationError: If every retry attempt fails, or the response
                was truncated before completion (hit ``max_tokens``).
        """
        return self.generate_multimodal(
            system_prompt=system_prompt,
            content=[{"type": "text", "text": user_prompt}],
            max_tokens=max_tokens,
        )

    def generate_multimodal(
        self,
        *,
        system_prompt: str,
        content: list[dict[str, Any]],
        max_tokens: int = 4096,
    ) -> str:
        """Request a single completion from mixed content blocks, retrying failures.

        ``content`` is the user turn's content list — any mix of ``text``,
        ``image``, and ``document`` (PDF) blocks. Claude reads PDFs and images
        natively (no beta header needed), so this is how the extractor lets the
        model analyse attachments the way a person would.

        Args:
            system_prompt: The system instructions for the request.
            content: The user-turn content blocks (text/image/document).
            max_tokens: Maximum tokens to generate.

        Returns:
            The concatenated text of the model's response.

        Raises:
            LLMGenerationError: If every retry attempt fails, or the response
                was truncated before completion (hit ``max_tokens``).
        """
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                messages = cast("list[MessageParam]", [{"role": "user", "content": content}])
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=messages,
                )
                if response.stop_reason == "max_tokens":
                    raise LLMGenerationError(
                        "LLM response was truncated (hit max_tokens); increase "
                        "max_tokens or shorten the prompt."
                    )
                return "".join(block.text for block in response.content if block.type == "text")
            except anthropic.APIError as exc:
                last_error = exc
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s", attempt, self._max_retries, exc
                )
                if attempt < self._max_retries:
                    time.sleep(2 ** (attempt - 1))

        raise LLMGenerationError(
            f"LLM call failed after {self._max_retries} attempts."
        ) from last_error


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    """Return the process-wide shared Anthropic LLM client."""
    return LLMClient(get_settings())
