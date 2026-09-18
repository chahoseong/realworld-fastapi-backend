# ADR 001: ORM 라이브러리로 SQLAlchemy를 사용한다

- 상태: 승인
- 결정일: 2026-09-18

## 맥락

이 프로젝트는 FastAPI와 PostgreSQL로 RealWorld 백엔드를 구현하면서 관계형 데이터 모델, session과 transaction 경계, API schema와 영속 모델의 책임을 학습하는 것을 목표로 한다.

ORM 라이브러리로 SQLAlchemy와 SQLModel을 검토했다.

## 결정

SQLAlchemy 2.x의 동기식 API를 사용한다.

API 요청·응답 모델은 Pydantic으로 정의하고, 영속 모델과 데이터베이스 접근은 SQLAlchemy가 담당한다.

## 근거

- SQLAlchemy는 session, transaction, mapping 등 데이터베이스 접근의 기본 개념을 직접 드러낸다.
- Pydantic API schema와 영속 모델의 책임을 명시적으로 분리할 수 있다.
- Alembic과 직접 연결되는 일반적인 구성이다.
- SQLModel이 제공하는 모델 통합과 코드 감소보다 책임 경계와 기본 원리의 가시성을 우선한다.

## 결과

- API schema와 영속 모델 사이에 일부 mapping 코드가 필요하다.
- SQLAlchemy의 session과 transaction을 애플리케이션에서 명시적으로 관리한다.
- SQLModel을 함께 사용하지 않는다.
