# Contributing

Install Python 3.14 and uv 0.12.x. From the repository root:

```powershell
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
uv build
```

Work on a feature branch and open a pull request; do not commit directly to `main`. Runtime code never reads environment variables or `.env` files. Consuming applications own environment loading and pass validated, typed configuration into runtime components.

Add dependencies only when implemented behavior justifies them. Ordinary contributions must not publish or release packages.
