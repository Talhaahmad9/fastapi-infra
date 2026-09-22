# Contributing

Install Python 3.14 and uv 0.12.x.

## Local Setup & Development

Install all development dependencies along with the PostgreSQL extra:

```powershell
uv sync --extra postgres
```

Run code formatting, linting, type checks, and unit tests:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pyright --verifytypes fastapi_infra --ignoreexternal
uv run pytest -m unit
uv build
```

## Running Integration and Hosted Tests

Integration tests require a running PostgreSQL instance and must be explicitly enabled using the `FASTAPI_INFRA_TEST_POSTGRES_DSN` environment variable:

```powershell
# Run local PostgreSQL integration tests against disposable database
$env:FASTAPI_INFRA_TEST_POSTGRES_DSN = "postgresql+psycopg://testuser:testpass@localhost:5432/testdb"
uv run pytest -m integration

# Run hosted smoke test against Supabase
$env:FASTAPI_INFRA_TEST_POSTGRES_DSN = "postgresql+psycopg://postgres:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres"
uv run pytest -m hosted
```

> **Warning**: Never commit database credentials, connection strings, or `.env` files to Git. Test credentials must only be injected via environment variables in local shells or temporary CI runners.

## Guidelines

Work on a feature branch and open a pull request; do not commit directly to `main`. Runtime code never reads environment variables or `.env` files. Consuming applications own environment loading and pass validated, typed configuration into runtime components.

Add dependencies only when implemented behavior justifies them. Ordinary contributions must not publish or release packages.
