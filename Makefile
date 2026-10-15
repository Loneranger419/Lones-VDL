.PHONY: check lint test install-dev run

install-dev:
	python -m pip install -e ".[dev]"

lint:
	python -m ruff check src tests
	python -m ruff format --check src tests

test:
	python -m pytest -q

check: lint test

run:
	python -m lones_vdl
