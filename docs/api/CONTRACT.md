# API Contract

## 기준 버전

- **공식 저장소:** [`realworld-apps/realworld`](https://github.com/realworld-apps/realworld)
- **기준 브랜치:** `main`
- **Commit:** [`ebbcdeb8d55b42a3a613c787560498b8ef10003f`](https://github.com/realworld-apps/realworld/commit/ebbcdeb8d55b42a3a613c787560498b8ef10003f)
- **선정일:** 2026-09-17
- **Tag/Release:** 선정일 기준 없음

공식 tag와 release가 없으므로, 선정 시점에 OpenAPI와 Hurl이 모두 포함된 공식 `main` 브랜치의 최신 commit을 기준으로 고정했다.

## Specs

- OpenAPI와 Hurl suite를 API Spec의 source of truth로 사용한다.
- Endpoints, API response format, Error handling은 OpenAPI와 Hurl suite에 명시되지 않은 배경과 공통 규칙을 보충하는 데 사용한다.
- 보충 자료는 OpenAPI와 Hurl suite의 명시된 요구사항을 변경하거나 약화하지 않는다.
- Hurl suite에서 검증하지 않는 요구사항도 OpenAPI에 명시되어 있으면 계약으로 유지한다.
- 자료 간 충돌이나 모호함은 임의로 해석하지 않고 사용자와 처리 방향을 논의한다.

### Links

- [OpenAPI](https://github.com/realworld-apps/realworld/blob/ebbcdeb8d55b42a3a613c787560498b8ef10003f/specs/api/openapi.yml)
- [Endpoints](https://github.com/realworld-apps/realworld/blob/ebbcdeb8d55b42a3a613c787560498b8ef10003f/docs/src/content/docs/specifications/backend/endpoints.md)
- [API response format](https://github.com/realworld-apps/realworld/blob/ebbcdeb8d55b42a3a613c787560498b8ef10003f/docs/src/content/docs/specifications/backend/api-response-format.md)
- [Error handling](https://github.com/realworld-apps/realworld/blob/ebbcdeb8d55b42a3a613c787560498b8ef10003f/docs/src/content/docs/specifications/backend/error-handling.md)

## Testing

- [Hurl](https://github.com/realworld-apps/realworld/tree/ebbcdeb8d55b42a3a613c787560498b8ef10003f/specs/api/hurl) — source of truth
- [Bruno](https://github.com/realworld-apps/realworld/tree/ebbcdeb8d55b42a3a613c787560498b8ef10003f/specs/api/bruno) — generated from Hurl
