.PHONY: install test lint typecheck check run e2e eval
install:
	python -m pip install -r requirements-dev.txt

test:
	pytest -q
lint:
	ruff check app tests scripts
format:
	ruff format app tests scripts
typecheck:
	mypy app
check: lint typecheck test
run:
	uvicorn app.main:app --reload

e2e:
	playwright install chromium
	pytest -q tests/e2e

eval:
	python scripts/evaluate_fixtures.py
