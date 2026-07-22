"""Thin wrapper around the Anthropic SDK.

Per the coding standards (file ``04``, rule 3.4), every external LLM call goes
through this module — services and agents never import ``anthropic``
directly. This is also the only place that applies the timeout and
exponential-backoff retry policy.
"""

from __future__ import annotations

import time

import anthropic

from src.config import Settings
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
        """Request a single completion, retrying transient failures.

        Args:
            system_prompt: The system instructions for the request.
            user_prompt: The user-turn content.
            max_tokens: Maximum tokens to generate.

        Returns:
            The concatenated text of the model's response.

        Raises:
            LLMGenerationError: If every retry attempt fails.
        """
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
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
