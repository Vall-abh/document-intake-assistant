# Contributing

## Local setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install `requirements-dev.txt`.
3. Copy `.env.example` to `.env`.
4. Use `LLM_PROVIDER=mock` for offline tests.
5. Run `python -m pytest`, `ruff check .`, and `mypy app` before opening a PR.

## Secrets and privacy

Never commit `.env`, API keys, SQLite databases, raw model recordings, or real user data. The live interview output file is ignored by Git because it may contain sensitive content. Add only sanitized regression fixtures.
