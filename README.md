# Document Intake Assistant v2

A production-oriented AI document-intake demo. It interviews a user, extracts structured facts, validates every proposed change deterministically, persists the session, and renders a fictional Personal Wishes Document.

**Not legal advice. The generated document is fictional and has no legal effect.**

## What is implemented

- FastAPI backend + plain HTML/JS UI.
- Provider-independent LLM layer with Google Gemini native structured output and Anthropic structured tool output.
- Deterministic Pydantic validation and state transitions after every model response.
- Evidence-aware grounding with safe contextual paraphrase matching.
- SQLite persistence, session expiry and versioned state-event history.
- Inline field editing through `PATCH` and an `undo` endpoint.
- PDF and DOCX export.
- Start-over confirmation in the UI.
- Rate limiting, request IDs, security headers and privacy-safe application logs.
- Retry/error metrics without logging message content.
- Rule-based mock + scripted replay mode for recorded real-model outputs.
- Unit/API tests plus an opt-in Playwright browser smoke test.
- Ruff/Mypy configuration, GitHub Actions, Dockerfile and Makefile.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate                 # Windows: .venv\\Scripts\\activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

Run quality checks:

```bash
make check
```

Run browser tests when Chromium is available:

```bash
make e2e
```

## Providers

### Offline mock

```env
LLM_PROVIDER=mock
```

The rule-based mock is intended for deterministic development/tests.

### Anthropic

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
LLM_MODEL=claude-sonnet-4-6
```

The client forces the provider to call the `submit_turn` tool. The application still parses and validates the returned payload, so provider-native structure is not treated as trust.

### Scripted replay

After recording a real interview:

```env
LLM_PROVIDER=scripted
```

The scripted provider replays `tests/fixtures/live_model_latest.json`, allowing demos and regression tests to reproduce real-model behavior without another API call.

## Architecture

```text
Browser
  │
  ▼
FastAPI /api/v1
  │
  ▼
ConversationService
  │
  ├── LLM provider ──► structured turn
  │                       │
  │                       ▼
  │                 Pydantic parser
  │                       │
  │                       ▼
  │                 deterministic validator
  │                       │
  │                       ▼
  ├──────────────► state transition
  │                       │
  │                       ▼
  └──────────────► SQLite event history
                          │
                          ▼
                    document renderer
```

The LLM **extracts**. Application code decides what can enter state.

## API

Versioned endpoints live under `/api/v1`; legacy `/api` endpoints remain for compatibility.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Health/provider status |
| POST | `/api/v1/sessions` | Create a session |
| GET | `/api/v1/sessions/{id}` | Read persisted session |
| POST | `/api/v1/sessions/{id}/messages` | Process a conversational turn |
| PATCH | `/api/v1/sessions/{id}/fields/{field}` | Directly edit a field |
| POST | `/api/v1/sessions/{id}/undo` | Undo the latest state version |
| GET | `/api/v1/sessions/{id}/history` | State-change history |
| GET | `/api/v1/sessions/{id}/export.pdf` | Download PDF |
| GET | `/api/v1/sessions/{id}/export.docx` | Download DOCX |
| GET | `/api/v1/metrics` | Aggregate turn/retry/error metrics |

## AI evaluation

Run a real interview with a configured Gemini or Anthropic provider:

```bash
LLM_PROVIDER=gemini python scripts/live_interview.py
```

The script refuses to fabricate a live run. It writes raw model outputs and parsed results to `tests/fixtures/live_model_latest.json`. Review those outputs, then keep the important failures as permanent regression fixtures.

Evaluate existing fixtures:

```bash
PYTHONPATH=. python scripts/evaluate_fixtures.py
```

The repository intentionally contains malformed fixtures too; rejection is expected for those cases.

## Security and privacy

- No application log records the user's message content.
- Text facts are not trusted merely because the model says `confirmed`.
- Evidence quotes must occur in the conversation.
- Rate limiting protects the LLM budget.
- Session expiry prevents indefinite retention in SQLite.
- API responses carry request IDs for troubleshooting.
- Production deployment should add authentication, a managed database and a distributed rate limiter.

## Testing

Current local suite: **57 passed, 1 skipped** (verify locally after installing dependencies). The skipped test is the Playwright smoke test unless `RUN_E2E=1` is set.

The test suite covers structured provider output, malformed output/retry behavior, grounding/paraphrases, corrections, contradictions, persistence, history, undo, exports, rate limiting and API behavior.

See `AI_LOG.md` for AI-specific evaluation notes and `PRODUCTION_NOTES.md` for deployment follow-ups.

## Using Google Gemini

The application supports Gemini as a first-class LLM provider. Gemini's native structured-output mode constrains responses to the `ModelTurn` Pydantic schema, while the application parser/validator remains the final safety net. Google documents JSON-schema/Pydantic structured output for the GenAI Python SDK.

Create `.env` from `.env.example` and set:

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
LLM_MODEL=gemini-2.5-flash
```

Then install dependencies and run:

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH=(Get-Location).Path
uvicorn app.main:app --reload
```

For a real recorded interview:

```powershell
python scripts/live_interview.py
```

The live interview stores model outputs in `tests/fixtures/live_model_latest.json`; do not commit secrets or raw sensitive user data.
