# User Registration Flow

이 문서는 회원가입 요청이 애플리케이션과 PostgreSQL을 거쳐 응답으로 반환되는 전체 흐름을 설명한다.

## Component Responsibilities

| 컴포넌트              | 책임                                                                              | 코드 위치                                                                                                                               |
| --------------------- | --------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| FastAPI Application   | 라우터와 예외 처리기를 연결하고 HTTP 요청과 응답의 경계를 제공한다.               | [`app/main.py::app`](../../../app/main.py)                                                                                             |
| Registration Endpoint | `POST /api/users` 경로를 제공하고 회원가입에 필요한 작업과 트랜잭션을 조정한다. | [`app/users/router.py::router, register_user()`](../../../app/users/router.py)                                                         |
| API Schemas           | 회원가입 요청을 검증하고 외부에 공개할 응답 구조를 정의한다.                      | [`app/users/schemas.py::NewUserRequest, NewUser, UserResponse`](../../../app/users/schemas.py)                                         |
| Security              | 비밀번호 해시와 사용자 ID를 식별하는 JWT를 생성한다.                              | [`app/security.py::hash_password(), create_access_token()`](../../../app/security.py)                                                  |
| Persistence           | 요청 범위 Session을 제공하고 사용자 데이터를 ORM 객체로 PostgreSQL에 저장한다.    | [`app/database.py::SessionDep, get_session()`](../../../app/database.py), [`app/users/models.py::User`](../../../app/users/models.py) |
| Error Handling        | 입력 검증 오류와 애플리케이션 오류를 API 오류 응답으로 변환한다.                  | [`app/errors.py::validation_error_handler(), api_error_handler()`](../../../app/errors.py)                                             |
| PostgreSQL            | 사용자 데이터를 영속화하고 필수값과 고유성 등의 제약 조건을 최종적으로 보장한다.  | [`0001_create_users_table.py`](../../../migrations/versions/0001_create_users_table.py)                                                |

## Runtime View

### 시나리오: User Registration

```mermaid
sequenceDiagram
    actor Client
    participant App as FastAPI Application
    participant Schemas as API Schemas
    participant Endpoint as Registration Endpoint
    participant Security
    participant Session as SQLAlchemy Session
    participant Database as PostgreSQL

    Client->>App: POST /api/users
    App->>Schemas: JSON body를 NewUserRequest로 검증
    Schemas-->>App: 검증된 요청
    App->>Endpoint: register_user(request, session)

    Endpoint->>Security: hash_password(password)
    Security-->>Endpoint: password_hash

    rect rgb(235, 251, 238)
        Note over Endpoint,Database: Transaction boundary
        Endpoint->>Session: begin()
        Endpoint->>Session: add(User), flush()
        Session->>Database: INSERT user
        Database-->>Session: generated user ID
        Session-->>Endpoint: user.id 할당 완료

        Endpoint->>Security: create_access_token(user.id)
        Security-->>Endpoint: JWT
        Endpoint->>Schemas: UserResponse 구성
        Schemas-->>Endpoint: 공개 응답

        Endpoint->>Session: transaction block 정상 종료
        Session->>Database: COMMIT
        Database-->>Session: commit 완료
    end

    Endpoint-->>App: UserResponse
    App-->>Client: 201 Created
```

- 비밀번호는 트랜잭션을 시작하기 전에 해싱하며, `flush()`로 할당된 사용자 ID를 JWT에 사용한다.
- 응답을 구성하는 동안 오류가 발생해도 저장이 확정되지 않도록 `UserResponse`를 트랜잭션 안에서 만들고, commit이 완료된 뒤 반환한다.
