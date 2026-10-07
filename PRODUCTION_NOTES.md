# Production Readiness Notes

Implemented in v2:

- SQLite persistence with session expiry and versioned state events.
- Direct field PATCH editing and undo/history endpoints.
- PDF and DOCX export.
- Provider-native structured output for Anthropic.
- Evidence-aware grounding and paraphrase handling.
- Rate limiting, request IDs, security headers and privacy-safe logs.
- Scripted model replay support.
- Playwright E2E smoke test (opt-in with `RUN_E2E=1`).
- Ruff, Mypy, pytest, coverage and GitHub Actions configuration.
- Dockerfile and Makefile.

Before a public deployment:

1. Put the database on managed PostgreSQL if multiple application replicas are needed.
2. Replace the in-process rate limiter with Redis/API-gateway limiting.
3. Store API secrets in a secret manager.
4. Add authentication/authorization around sessions.
5. Run the real-model evaluation suite and review every new fixture before release.
6. Run `make check` and `make e2e` in CI with the required tools installed.


### Gemini as a live evaluation provider

The live interview harness now supports both `gemini` and `anthropic`. Gemini is the recommended zero-Anthropic-credit path for local evaluation when a Gemini API key is available. Structured output is enforced through the Google GenAI SDK's JSON-schema/Pydantic response configuration.
