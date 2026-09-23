# AGENTS.md

## Commands

프로젝트 루트에서 실행한다.

Type hint:

- `uv run mypy`     # python

Lint:

File-Scoped
- `uv run ruff check path/to/file.py`
- `uv run ruff check --fix path/to/file.py`

Directory-Scoped
- `uv run ruff check path/to/directory/`
- `uv run ruff check --fix path/to/directory/`

Full Suite
- `uv run ruff check .`

Format:

File-Scoped
- `uv run ruff format --check path/to/file.py`
- `uv run ruff format path/to/file.py`

Directory-Scoped
- `uv run ruff format --check path/to/directory/`
- `uv run ruff format path/to/directory/`

Full Suite
- `uv run ruff format --check .`

## Testing

### Strcture

```text
tests/
├── unit/
├── integration/
├── api/            # hurl
```

### Running Tests

- `uv run pytest tests/unit/`
- `uv urn pytest tests/integration/`


## API 계약

- API 관련 구현이나 검토를 시작하기 전에 [`docs/api/CONTRACT.md`](docs/api/CONTRACT.md)를 확인하고, 그 문서에 고정된 공식 계약을 기준으로 사용한다.
- 계약 기준 버전을 임의로 변경하지 않는다. 변경이 필요하면 영향과 이유를 먼저 사용자와 논의한다.