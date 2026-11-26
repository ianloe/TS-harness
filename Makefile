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
	uv run ts-harness eval

attest:
	uv run ts-harness attest
