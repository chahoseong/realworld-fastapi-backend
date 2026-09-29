# Render에 배포하기

이 프로젝트를 Render의 Python 웹 서비스와 Render Postgres로 배포하는 방법을 소개합니다. Render 계정과 프로젝트 저장소 접근이 준비된 상태에서 시작합니다.

## DB 연결 준비하기

1. Render Postgres에서 PostgreSQL 18 DB를 준비합니다. 생성 절차는 [Render Postgres 문서](https://render.com/docs/postgresql-creating-connecting)를 참고하세요.
2. DB의 **Info**에서 **Internal Database URL**을 복사합니다.
3. URL 맨 앞의 `postgresql://`를 `postgresql+psycopg://`로 바꿉니다. 이 값을 웹 서비스의 `DATABASE_URL`에 사용합니다.

## 웹 서비스 설정하기

1. 프로젝트 저장소로 [Python 웹 서비스](https://render.com/docs/web-services)를 준비합니다. DB와 같은 Render 계정·리전을 사용하세요. 이 사례에서는 Singapore를 선택했습니다.
2. **Language**는 `Python 3`, **Branch**는 배포할 코드가 있는 브랜치로 설정합니다. 이 사례에서는 `master`를 사용했습니다. **Root Directory**는 비워 저장소 루트에서 실행합니다.
3. **Environment**에 다음 값을 입력합니다.

   | 변수               | 값                                                                            |
   | ------------------ | ----------------------------------------------------------------------------- |
   | `PYTHON_VERSION` | `3.14.5`                                                                    |
   | `UV_VERSION`     | `0.12.15`                                                                   |
   | `DATABASE_URL`   | DB 연결 준비 단계에서 만든 내부 DB 접속 URL                                   |
   | `JWT_SECRET_KEY` | [README의 생성 명령](../../README.md#configure-environment)으로 만든 배포용 키 |
4. **Build Command**에 입력합니다.

   ```bash
   uv sync --locked --no-dev
   ```
5. **Start Command**에 입력합니다.

   ```bash
   uv run --no-sync alembic upgrade head && uv run --no-sync alembic current && exec uv run --no-sync fastapi run --host 0.0.0.0 --port $PORT
   ```
6. **Auto-Deploy**는 `Off`, **Health Check Path**는 `/openapi.json`으로 설정합니다.

## 배포하고 확인하기

1. 웹 서비스를 배포합니다. 특정 버전을 배포하려면 **Manual Deploy > Deploy a specific commit**에서 커밋 ID를 지정합니다. 같은 버전을 다시 배포할 때는 같은 커밋 ID와 Python·uv 버전을 사용하세요. [수동 배포 절차](https://render.com/docs/deploys#manual-deploys)를 참고할 수 있습니다.
2. **Deploys > Source**에 원하는 커밋 ID가 표시되는지 확인합니다.
3. **Logs**에서 마이그레이션의 최신 버전 적용 표시인 `(head)`와 `Application startup complete`를 확인합니다.
4. 서비스의 HTTPS 주소에 `/openapi.json`을 붙여 요청하고 HTTP 200을 확인합니다.
5. 저장·조회와 인증 동작은 [Hurl 테스트](../../tests/api/README.md)로 확인합니다. `host`에는 서비스의 HTTPS 주소를 `/api` 없이 넣고, `uid`에는 새 실행 식별자를 넣습니다. 테스트는 계정과 데이터를 생성하므로 검증용 환경에서 실행하세요.

## 재시작하거나 종료하기

- 재시작: **Manual Deploy > Restart service**를 실행합니다. 기존 게시글을 같은 URL로 조회해 내용이 유지되는지 확인합니다.
- 잠시 중지: 웹 서비스 **Settings > Suspend Web Service**를 사용합니다. 다시 실행할 때는 대시보드에서 **Resume**을 선택합니다. [중지·재개 안내](https://render.com/changelog/suspend-and-resume-services-in-bulk-from-the-render-dashboard)를 참고하세요.
- 환경 제거: 웹 서비스 **Settings > Delete Web Service**, DB **Info > Delete Database**로 각각 삭제합니다. DB 삭제 전 필요한 데이터를 보존하세요. 웹 서비스를 중지하거나 삭제해도 DB는 별도로 남습니다.

삭제 후 다시 배포하려면 새 DB의 접속 URL을 `DATABASE_URL`에 넣고 이 절차를 따릅니다.
