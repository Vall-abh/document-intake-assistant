"""Anthropic Messages API client with provider-native structured tool output."""
import json
import logging

import httpx

from app.llm.base import LLMNotConfigured, LLMUnavailable
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.schemas import ModelTurn, TurnRequest

logger = logging.getLogger(__name__)
API_URL = "https://api.anthropic.com/v1/messages"
TOOL_NAME = "submit_turn"


def _turn_tool() -> dict:
    schema = ModelTurn.model_json_schema()
    return {
        "name": TOOL_NAME,
        "description": "Return the validated interview updates and a short reply.",
        "input_schema": schema,
    }


class AnthropicClient:
    name = "anthropic"
    is_configured = True

    def __init__(self, api_key: str, model: str, timeout: float = 30.0, http: httpx.Client | None = None):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._http = http or httpx.Client()

    def complete(self, request: TurnRequest) -> str:
        payload = {
            "model": self._model,
            "max_tokens": 1024,
            "system": SYSTEM_PROMPT,
            "tools": [_turn_tool()],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
            "messages": [{"role": "user", "content": build_user_prompt(request)}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            response = self._http.post(API_URL, json=payload, headers=headers, timeout=self._timeout)
        except httpx.TimeoutException as exc:
            raise LLMUnavailable("The language model timed out. Please try again.") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable("Could not reach the language model. Please try again.") from exc

        if response.status_code in (401, 403):
            raise LLMNotConfigured("The language model rejected the API key. Check ANTHROPIC_API_KEY.")
        if response.status_code >= 400:
            logger.warning("LLM provider returned HTTP %s", response.status_code)
            raise LLMUnavailable(f"The language model returned an error (HTTP {response.status_code}).")

        try:
            blocks = response.json().get("content", [])
            for block in blocks:
                if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
                    return json.dumps(block.get("input", {}), ensure_ascii=False)
            # Keep the parser as the safety net if a provider/proxy ignores tool_choice.
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (ValueError, AttributeError, TypeError) as exc:
            raise LLMUnavailable("The language model returned an unreadable response.") from exc
