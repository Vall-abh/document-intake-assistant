"""Google Gemini client using provider-native JSON schema structured output."""
from __future__ import annotations

import logging

from app.llm.base import LLMNotConfigured, LLMUnavailable
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.schemas import ModelTurn, TurnRequest

logger = logging.getLogger(__name__)


class GeminiClient:
    """Gemini API adapter with JSON-schema constrained ModelTurn output."""

    name = "gemini"
    is_configured = True

    def __init__(self, api_key: str, model: str, timeout: float = 30.0):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise LLMNotConfigured(
                "Gemini support requires google-genai. Run: pip install -r requirements.txt"
            ) from exc

        self._types = types
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._timeout = timeout

    def complete(self, request: TurnRequest) -> str:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=build_user_prompt(request),
                config=self._types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=ModelTurn,
                    temperature=0.0,
                    max_output_tokens=1024,
                ),
            )
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            if "api key" in lowered or "permission" in lowered or "unauthenticated" in lowered:
                raise LLMNotConfigured(
                    "Gemini rejected the API key. Check GEMINI_API_KEY."
                ) from exc
            if "timeout" in lowered or "deadline" in lowered:
                raise LLMUnavailable("The Gemini model timed out. Please try again.") from exc
            logger.warning("Gemini request failed: %s", message)
            raise LLMUnavailable(f"The Gemini model returned an error: {message}") from exc

        text = getattr(response, "text", None)
        if not text:
            parsed = getattr(response, "parsed", None)
            if parsed is not None:
                return parsed.model_dump_json() if hasattr(parsed, "model_dump_json") else str(parsed)
            raise LLMUnavailable("The Gemini model returned an empty response.")
        return text
