# Install (or refresh) the commands into ~/.local/bin as an editable uv tool.
sync:
    uv tool install --editable . --reinstall

test *args:
    uv run pytest {{args}}

lint:
    uv run ruff check .
    uv run ruff format --check .

fmt:
    uv run ruff check --fix .
    uv run ruff format .
