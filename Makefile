.PHONY: setup test lint run eval attest

setup:
	uv sync --extra dev

test:
	uv run pytest

lint:
	uv run ruff check src tests
	uv run mypy src

run:
	uv run ts-harness status

eval:
	@echo "Evaluation harness will be enabled in Phase 5."

attest:
	@echo "Attestation report generator will be enabled in Phase 6."
