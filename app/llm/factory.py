from app.config import Settings
from app.llm.anthropic_client import AnthropicClient
from app.llm.gemini_client import GeminiClient
from app.llm.base import LLMClient, LLMNotConfigured
from app.llm.mock_client import MockLLMClient


def build_llm_client(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return MockLLMClient()
    if provider == "scripted":
        from pathlib import Path
        fixture = Path("tests/fixtures/live_model_latest.json")
        if not fixture.exists():
            raise LLMNotConfigured("Scripted provider requires tests/fixtures/live_model_latest.json.")
        from app.llm.scripted import ScriptedLLMClient
        return ScriptedLLMClient(str(fixture))
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMNotConfigured("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set.")
        return GeminiClient(settings.gemini_api_key, settings.llm_model, settings.llm_timeout_seconds)
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMNotConfigured("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set.")
        return AnthropicClient(settings.anthropic_api_key, settings.llm_model, settings.llm_timeout_seconds)
    raise LLMNotConfigured(f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use 'mock', 'gemini', or 'anthropic'.")
