import httpx
import pytest

from app.config import Settings
from app.llm.anthropic_client import AnthropicClient
from app.llm.base import LLMNotConfigured, LLMUnavailable
from app.llm.factory import build_llm_client
from app.schemas import TurnRequest, WishesState


def req():
    return TurnRequest(state=WishesState(), missing_fields=[], unconfirmed_fields=[], pending_field=None,
                       history=[], user_message="hi")


def client(handler):
    return AnthropicClient("key", "model", http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_success_uses_forced_structured_tool_and_returns_tool_input():
    seen = {}

    def handler(request):
        seen["key"] = request.headers["x-api-key"]
        payload = request.read().decode()
        seen["payload"] = __import__("json").loads(payload)
        return httpx.Response(200, json={"content": [{
            "type": "tool_use", "name": "submit_turn", "id": "tool-1",
            "input": {"updates": [], "reply": "ok"}
        }]})

    assert client(handler).complete(req()) == '{"updates": [], "reply": "ok"}'
    assert seen["key"] == "key"
    assert seen["payload"]["tool_choice"] == {"type": "tool", "name": "submit_turn"}
    assert seen["payload"]["tools"][0]["name"] == "submit_turn"


@pytest.mark.parametrize("status,exc", [(401, LLMNotConfigured), (429, LLMUnavailable), (500, LLMUnavailable)])
def test_http_errors_are_mapped(status, exc):
    with pytest.raises(exc):
        client(lambda r: httpx.Response(status, json={})).complete(req())


def test_timeout_is_mapped():
    def handler(request):
        raise httpx.ReadTimeout("slow")
    with pytest.raises(LLMUnavailable):
        client(handler).complete(req())


def test_factory_reports_missing_key_and_unknown_provider():
    with pytest.raises(LLMNotConfigured):
        build_llm_client(Settings(llm_provider="anthropic"))
    with pytest.raises(LLMNotConfigured):
        build_llm_client(Settings(llm_provider="nope"))


def test_factory_reports_missing_gemini_key():
    with pytest.raises(LLMNotConfigured, match="GEMINI_API_KEY"):
        build_llm_client(Settings(llm_provider="gemini"))
