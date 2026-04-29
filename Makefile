.PHONY: install dev test clean lint

# Install into a dedicated venv for the MCP server runtime
install:
	uv venv ~/.config/vw-bridge/venv
	uv pip install -e . --python ~/.config/vw-bridge/venv/bin/python

# Dev install with test/lint deps
dev:
	uv venv .venv
	uv pip install -e ".[dev]" --python .venv/bin/python

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check vw_bridge/ tests/

clean:
	rm -rf build/ dist/ *.egg-info/ .pytest_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
