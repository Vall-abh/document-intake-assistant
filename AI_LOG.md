# AI Engineering Log

## Evaluation policy

The LLM is an extractor, never the source of truth. Provider output is parsed against a Pydantic contract; deterministic validation decides what enters state.

## Recorded model behavior

- Provider-native Anthropic `submit_turn` tool use is forced.
- Malformed structured output is retried once, then the turn is rejected without changing state.
- Text values are grounded against the user's conversation. Paraphrased phrases such as `watch to Tom` can match `my watch to my son Tom`; invented names remain unconfirmed.
- Model-provided evidence quotes are accepted only when the evidence appears in the conversation.
- Multi-update messages are supported; each update is validated independently.
- Contradictions are surfaced as explicit conflicts instead of being silently resolved by the model.

## Real-model evaluation

Run `ANTHROPIC_API_KEY=... python scripts/live_interview.py` to record a real Anthropic interview in `tests/fixtures/live_model_latest.json`. The script refuses to fabricate a live run when a key is unavailable.

Run `python scripts/evaluate_fixtures.py` to validate recorded outputs.

## Privacy/cost controls

Message content is not logged by the application. Metrics track turn count, retry count, errors and latency without storing prompts. Retry count is exposed so model-cost impact is measurable.


## Gemini provider support

Added a first-class Google Gemini provider using the official `google-genai` SDK. Gemini is configured with `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, and a configurable `LLM_MODEL` (default `gemini-2.5-flash`). The provider uses native JSON structured output against the same `ModelTurn` Pydantic contract used by the application, preserving the deterministic parser/validator as the final safety layer.
