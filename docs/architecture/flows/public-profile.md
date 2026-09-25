# Public Profile Retrieval Flow

이 문서는 사용자의 공개 프로필을 조회하는 흐름을 설명한다.

## Component Responsibilities

| 컴포넌트                | 책임                                                                       | 코드 위치                                                                                                                |
| ----------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| FastAPI Application     | 프로필 라우터와 오류 처리기를 연결한다.                                    | [`app/main.py::app`](../../../app/main.py)                                                                              |
| Profile Endpoint        | 경로의`username`으로 대상 사용자를 조회하고 공개 프로필 응답을 구성한다. | [`app/users/router.py::get_profile()`](../../../app/users/router.py)                                                    |
| Optional Authentication | 헤더가 없으면 익명 요청을 허용하고, 있으면 토큰으로 요청자를 식별한다.     | [`app/users/auth.py::get_optional_user(), OptionalUserDep`](../../../app/users/auth.py)                                 |
| Security                | 전달된 JWT의 서명과 만료를 검증한다.                                       | [`app/security.py::decode_access_token()`](../../../app/security.py)                                                    |
| Persistence             | 요청자 인증과 대상 프로필 조회에 필요한 사용자를 DB에서 찾는다.            | [`app/database.py::SessionDep`](../../../app/database.py), [`app/users/models.py::User`](../../../app/users/models.py) |
| Profile Response Schema | `username`, `bio`, `image`, `following`만 응답에 담는다.           | [`app/users/schemas.py::ProfilePayload, ProfileResponse`](../../../app/users/schemas.py)                                |
| Error Handling          | 잘못된 토큰과 없는 프로필을 API 오류 응답으로 변환한다.                    | [`app/errors.py::api_error_handler()`](../../../app/errors.py)                                                          |

## Runtime View

### 시나리오: 공개 프로필 조회

```mermaid
sequenceDiagram
    actor Client
    participant App as FastAPI Application
    participant Auth as Optional Authentication
    participant Endpoint as Profile Endpoint
    participant Session as SQLAlchemy Session
    participant Database as PostgreSQL

    Client->>App: GET /api/profiles/{username}
    App->>Auth: get_optional_user(session, request)
    alt Authorization 헤더 없음
        Auth-->>App: None (익명 요청)
    else Authorization 헤더 있음
        Auth->>Auth: 토큰 검증·사용자 확인
        Auth-->>App: viewer: User
    end
    App->>Endpoint: get_profile(username, session, _viewer)
    Endpoint->>Session: username으로 대상 사용자 조회
    Session->>Database: SELECT user
    Database-->>Session: 대상 사용자
    Session-->>Endpoint: 대상 사용자
    Endpoint-->>App: ProfileResponse (공개 필드)
    App-->>Client: 200 OK
```
