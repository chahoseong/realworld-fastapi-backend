> ### [YOUR_FRAMEWORK] codebase containing real world examples (CRUD, auth, advanced patterns, etc) that adheres to the [RealWorld](https://github.com/gothinkster/realworld) spec and API.

### [Demo](https://demo.realworld.build/)&nbsp;&nbsp;&nbsp;&nbsp;[RealWorld](https://github.com/gothinkster/realworld)

This codebase was created to demonstrate a fully fledged fullstack application built with **[YOUR_FRAMEWORK]** including CRUD operations, authentication, routing, pagination, and more.

We've gone to great lengths to adhere to the **[YOUR_FRAMEWORK]** community styleguides & best practices.

For more information on how to this works with other frontends/backends, head over to the [RealWorld](https://github.com/gothinkster/realworld) repo.

# How it works

> Describe the general architecture of your app here

# Getting started

## Prerequisites

Install the following tools before setting up the project:

- [Python 3.14](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Docker](https://docs.docker.com/get-started/get-docker/) with Docker Compose

## Install dependencies

```bash
uv sync
```

## Configure environment

```text
DATABASE_URL=PostgreSQL connection URL used by the application; the example matches the db service in compose.yaml
TEST_DATABASE_URL=PostgreSQL connection URL used by integration tests; it must target the isolated realworld_test database
JWT_SECRET_KEY=Secret used to sign and verify JWTs; use at least 32 random bytes and never commit the real value
```

- Generate `JWT_SECRET_KEY`: `uv run python -c "import secrets; print(secrets.token_hex(32))"`

## Run the application

Start PostgreSQL:

```bash
docker compose up -d --wait db
```

Apply migrations:

```bash
uv run alembic upgrade head
```

Run the API:

```bash
uv run fastapi dev
```

- The API is available at `http://127.0.0.1:8000`, and the OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

Stop the application and environment:

- API: Press `Ctrl+C` in the terminal.
- PostgreSQL:

  ```bash
  docker compose stop db
  ```

# Testing

## Integration tests

Start the isolated PostgreSQL test database:

```bash
docker compose --profile test up -d --wait test-db
```

Run the integration tests:

```bash
uv run pytest tests/integration
```

- The test setup verifies that `TEST_DATABASE_URL` targets the `realworld_test` database and applies migrations automatically.

Stop the test database:

```bash
docker compose --profile test stop test-db
```

## API contract tests

Hurl tests verify the public HTTP API against the fixed RealWorld contract.

See [`tests/api/README.md`](tests/api/README.md) for prerequisites and commands.
