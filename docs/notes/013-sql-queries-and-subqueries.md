# SQL 조회와 서브쿼리

이 노트는 SQL(Structured Query Language)로 데이터를 조회하고, 다른 테이블의 정보를 조회 조건에 사용하는 방법을 설명한다. 먼저 작은 데이터로 조회 결과가 어떻게 만들어지는지 살펴보고, 마지막에 프로젝트의 SQLAlchemy 코드와 연결한다. 테이블과 관계를 설계하는 원리는 [관계형 데이터 모델링과 참조 무결성](009-relational-data-modeling-and-referential-integrity.md)에서 다룬다.

## `SELECT`·`FROM`·`WHERE`로 조회하기

쿼리(Query)는 데이터베이스에 데이터를 조회하거나 처리하도록 요청하는 문장이다. 여기서는 조회에 사용하는 `SELECT` 문(SELECT Statement)을 다룬다. 조회 결과는 행(Row)과 열(Column)로 구성된 결과 집합(Result Set)이다.

다음 학생·강좌·수강 데이터를 공통 예제로 사용한다. `enrollments`의 한 행은 학생 한 명이 강좌 하나를 수강한다는 사실을 나타낸다.

**학생 테이블 `students`**

| id | name |
| --- | --- |
| 1 | 민지 |
| 2 | 준호 |
| 3 | 소연 |

**강좌 테이블 `courses`**

| id | title | created_at |
| --- | --- | --- |
| 10 | 데이터베이스 | 2026-09-28 09:00:00 |
| 20 | 네트워크 | 2026-09-28 09:00:00 |
| 30 | 운영체제 | 2026-09-29 09:00:00 |

**수강 테이블 `enrollments`**

| student_id | course_id |
| --- | --- |
| 1 | 10 |
| 1 | 20 |
| 2 | 10 |

강좌 중 ID가 20 이상인 강좌의 ID와 제목을 조회한다.

```sql
SELECT id, title
FROM courses
WHERE id >= 20;
```

| 절(Clause) | 역할 | 이 예시의 의미 |
| --- | --- | --- |
| `SELECT` | 결과에 포함할 열이나 표현식(Expression)을 지정한다. | ID와 제목을 표시한다. |
| `FROM` | 조회할 데이터의 출처를 지정한다. | 강좌 테이블을 사용한다. |
| `WHERE` | 조건을 만족하는 행만 선택한다. | ID가 20 이상인 강좌를 선택한다. |

결과에 포함되는 행은 다음과 같다. 정렬 조건이 없는 예시의 결과표는 읽기 쉽게 배열한 것이며, 실제 반환 순서를 보장하지 않는다.

| id | title |
| --- | --- |
| 20 | 네트워크 |
| 30 | 운영체제 |

이 쿼리를 이해할 때는 **강좌 테이블에서 → 조건에 맞는 행을 선택하고 → ID와 제목을 표시한다**고 읽으면 된다. 이는 결과의 의미를 설명하는 순서다. 데이터베이스의 실제 실행 순서는 쿼리 최적화기(Query Optimizer)가 정하는 실행 계획(Execution Plan)에 따라 달라질 수 있다.

`SELECT *`는 조회 대상의 모든 열을 선택한다. `SELECT id, title`은 필요한 열만 선택한다. 두 쿼리 모두 `WHERE` 조건이 같다면 같은 강좌들을 대상으로 하지만, 결과의 열 구성은 다르다.

## `JOIN`으로 테이블 연결하기

조인(Join)은 조건에 따라 두 조회 대상의 행을 연결한다. 연결 조건(Join Condition)은 보통 `ON` 절에 적는다. 테이블 별칭(Table Alias)은 쿼리 안에서 테이블을 가리키는 이름이며, `students AS s`는 학생 테이블을 `s`로 부른다는 뜻이다.

### 내부 조인: 조건에 맞는 행끼리 연결하기

내부 조인(Inner Join, `INNER JOIN`)으로 학생 이름과 수강 중인 강좌 제목을 함께 조회한다.

```sql
SELECT s.id, s.name, c.title
FROM students AS s
INNER JOIN enrollments AS e ON e.student_id = s.id
INNER JOIN courses AS c ON c.id = e.course_id;
```

| id | name | title |
| --- | --- | --- |
| 1 | 민지 | 데이터베이스 |
| 1 | 민지 | 네트워크 |
| 2 | 준호 | 데이터베이스 |

민지는 수강 행 두 개와 연결되므로 결과에 두 번 나타난다. 소연은 연결할 수강 행이 없으므로 결과에 나타나지 않는다. **이 결과의 한 행은 학생 한 명이 아니라, 학생과 수강 강좌의 조합 하나다.**

다음처럼 강좌 제목을 결과에서 빼도 민지의 행은 두 개다.

```sql
SELECT s.id, s.name
FROM students AS s
INNER JOIN enrollments AS e ON e.student_id = s.id;
```

| id | name |
| --- | --- |
| 1 | 민지 |
| 1 | 민지 |
| 2 | 준호 |

`SELECT`에서 열을 줄인다고 연결된 행들이 자동으로 합쳐지지는 않는다. `SELECT DISTINCT s.id, s.name`처럼 `DISTINCT`를 지정하면 **선택한 열의 값이 모두 같은 결과 행**을 중복 제거할 수 있다. 수강 여부만 확인하려는 경우에는 뒤에서 다룰 `EXISTS`로 목적을 직접 표현할 수도 있다. [PostgreSQL의 중복 제거 설명](https://www.postgresql.org/docs/18/queries-select-lists.html#QUERIES-DISTINCT)

### 왼쪽 외부 조인: 연결할 행이 없어도 왼쪽 행 유지하기

왼쪽 외부 조인(Left Outer Join, `LEFT JOIN`)은 왼쪽 대상의 행을 유지한다. 연결 조건에 맞는 오른쪽 행이 없으면 오른쪽 열은 널(NULL)로 표시한다.

```sql
SELECT s.id, s.name, e.course_id
FROM students AS s
LEFT JOIN enrollments AS e ON e.student_id = s.id;
```

| id | name | course_id |
| --- | --- | --- |
| 1 | 민지 | 10 |
| 1 | 민지 | 20 |
| 2 | 준호 | 10 |
| 3 | 소연 | NULL |

`NULL`은 값이 없거나 알려지지 않았음을 표현한다. 여기서는 소연과 연결된 수강 행이 없다는 의미다. `LEFT JOIN`도 여러 오른쪽 행이 연결되면 왼쪽 행이 여러 번 나타날 수 있다.

외부 조인에서는 조건의 위치도 중요하다. 위 쿼리에 `WHERE e.course_id = 10`을 추가하면 소연의 행은 제외된다. 조인이 유지한 행이라도, 이후 `WHERE` 조건을 만족해야 최종 결과에 남기 때문이다. 강좌 10의 수강 정보만 연결하면서 모든 학생을 유지하려면 그 조건을 `ON`에 둔다.

```sql
SELECT s.id, s.name, e.course_id
FROM students AS s
LEFT JOIN enrollments AS e
    ON e.student_id = s.id AND e.course_id = 10;
```

이 경우 민지와 준호는 강좌 10과 연결되고, 소연은 `course_id`가 `NULL`인 행으로 남는다. 조인의 종류와 `ON`·`WHERE`의 차이는 [PostgreSQL의 테이블 표현식 설명](https://www.postgresql.org/docs/18/queries-table-expressions.html#QUERIES-JOIN)에서 확인할 수 있다.

## 서브쿼리란 무엇인가

서브쿼리(Subquery)는 다른 SQL 문 안에 포함된 조회 문이다. **어디에 사용하며, 결과가 어떤 형태여야 하는지**를 함께 봐야 한다.

### 값 하나로 사용하기: 스칼라 서브쿼리

스칼라 서브쿼리(Scalar Subquery)는 한 열의 값 하나를 바깥 표현식에 제공한다. 강좌 제목이 고유하다고 가정하고, 데이터베이스 강좌를 수강하는 학생을 찾는다.

```sql
SELECT s.id, s.name
FROM students AS s
INNER JOIN enrollments AS e ON e.student_id = s.id
WHERE e.course_id = (
    SELECT c.id
    FROM courses AS c
    WHERE c.title = '데이터베이스'
);
```

안쪽 조회의 결과는 `10`이다. 바깥 조건은 `e.course_id = 10`으로 이해할 수 있으며, 결과에는 민지와 준호가 포함된다.

스칼라 서브쿼리는 **한 열, 최대 한 행**이어야 한다. 여러 행이나 여러 열을 반환하면 오류다. 행이 없으면 값은 `NULL`로 취급된다. 이 예시에서 같은 제목의 강좌가 여러 개라면 어떤 ID를 비교해야 할지 정할 수 없으므로 오류가 발생한다. [PostgreSQL의 스칼라 서브쿼리 설명](https://www.postgresql.org/docs/18/sql-expressions.html#SQL-SYNTAX-SCALAR-SUBQUERIES)

### 여러 값과 비교하기: `IN`

`IN`은 왼쪽 값이 오른쪽의 값들 중 하나와 일치하는지 확인한다. 민지가 수강하는 강좌들을 조회한다.

```sql
SELECT c.id, c.title
FROM courses AS c
WHERE c.id IN (
    SELECT e.course_id
    FROM enrollments AS e
    WHERE e.student_id = 1
);
```

안쪽 조회는 `10`, `20`을 반환한다. 바깥 쿼리는 ID가 그 값들 중 하나인 강좌를 선택하므로 데이터베이스와 네트워크 강좌가 포함된다. 이 형태의 `IN`에는 한 열의 여러 행을 반환하는 서브쿼리를 사용할 수 있다.

### 조회 대상 테이블로 사용하기: 파생 테이블

서브쿼리를 `FROM` 절에 놓으면 그 결과를 조회 대상으로 사용할 수 있다. 이를 파생 테이블(Derived Table)이라고 한다.

```sql
SELECT selected_courses.id, selected_courses.title
FROM (
    SELECT id, title
    FROM courses
    WHERE id >= 20
) AS selected_courses
WHERE selected_courses.title = '운영체제';
```

안쪽 결과에는 네트워크와 운영체제 강좌가 있고, 바깥 조건은 그중 운영체제를 선택한다. `selected_courses`는 서브쿼리 결과의 별칭이며, 실제 테이블을 새로 만드는 것은 아니다.

| 사용 형태 | 안쪽 결과를 사용하는 방법 |
| --- | --- |
| 스칼라 서브쿼리 | 값 하나로 비교하거나 결과 열에 표시한다. |
| `IN (서브쿼리)` | 조회된 값들 중 일치하는 값이 있는지 비교한다. |
| `FROM (서브쿼리) AS 별칭` | 조회 결과를 바깥 쿼리의 데이터 출처로 사용한다. |

괄호 안의 조회가 끝나야 다음 Python 코드를 실행한다는 뜻은 아니다. 세 형태 모두 **하나의 SQL 문**으로 데이터베이스에 전달할 수 있으며, 실제 처리 방법은 데이터베이스가 결정한다.

## 상관 서브쿼리로 바깥 행 참조하기

상관 서브쿼리(Correlated Subquery)는 안쪽 쿼리가 바깥 쿼리의 열을 참조하는 서브쿼리다. 다음은 수강 중인 강좌가 있는 학생을 선택하는 쿼리다. `EXISTS`의 의미는 다음 절에서 자세히 살펴본다.

```sql
SELECT s.id, s.name
FROM students AS s
WHERE EXISTS (
    SELECT 1
    FROM enrollments AS e
    WHERE e.student_id = s.id
);
```

`s`는 바깥에서 정의한 학생 테이블 별칭이다. 안쪽의 `e.student_id = s.id`가 **현재 확인하는 학생과 수강 행을 연결하는 조건**이다.

| 바깥에서 확인하는 학생 | 안쪽 조건의 의미 | 일치하는 수강 정보 |
| --- | --- | --- |
| 민지, `s.id = 1` | `e.student_id = 1` | 강좌 10, 20의 수강 행 |
| 준호, `s.id = 2` | `e.student_id = 2` | 강좌 10의 수강 행 |
| 소연, `s.id = 3` | `e.student_id = 3` | 없음 |

앞의 `IN` 예시는 `student_id = 1`이라는 고정 조건을 사용했다. 여기서는 **바깥 행의 학생 ID에 따라 확인할 수강 정보가 달라진다.** 스칼라 서브쿼리나 `EXISTS` 안에서도 이런 참조를 사용할 수 있다.

이 표는 쿼리의 의미를 행별로 읽는 방법이다. 데이터베이스가 반드시 학생마다 안쪽 SQL을 별도로 실행한다거나, 애플리케이션이 학생 수만큼 DB 요청을 보낸다는 뜻은 아니다. 쿼리 최적화기는 의미를 유지하는 실행 계획을 선택한다. SQLAlchemy에서의 바깥 열 참조는 [스칼라·상관 서브쿼리 설명](https://docs.sqlalchemy.org/en/20/tutorial/data_select.html#scalar-and-correlated-subqueries)을 참고할 수 있다.

## `EXISTS`로 존재 여부 확인하기

`EXISTS`는 서브쿼리의 결과에 행이 하나라도 있으면 참(True), 없으면 거짓(False)이 되는 존재 여부 표현식이다. `WHERE EXISTS (...)`는 이 값이 참인 바깥 행만 유지한다.

위 학생 조회의 결과는 다음과 같다.

| id | name |
| --- | --- |
| 1 | 민지 |
| 2 | 준호 |

민지의 수강 행은 두 개지만, `EXISTS`의 결과는 **참이라는 조건 하나**다. 안쪽 수강 행들을 바깥 결과에 붙이지 않으므로, 학생 테이블의 민지 행은 한 번만 포함된다.

`SELECT 1`은 안쪽에서 일치한 각 행에 상수 `1`을 선택한다는 뜻이다. **한 행으로 제한한다는 뜻이 아니다.** 이 예시는 행의 존재만 확인하므로 `SELECT e.course_id`를 사용해도 `EXISTS`의 판단은 같다. 선택한 값 자체를 바깥 결과로 반환하지 않기 때문이다.

`NOT EXISTS`는 반대 조건이다. 안쪽에 일치하는 행이 없을 때 참이므로, 수강 중인 강좌가 없는 학생을 찾을 수 있다.

```sql
SELECT s.id, s.name
FROM students AS s
WHERE NOT EXISTS (
    SELECT 1
    FROM enrollments AS e
    WHERE e.student_id = s.id
);
```

결과에는 소연 한 명이 포함된다. `EXISTS`의 정의와 바깥 행 참조는 [PostgreSQL의 서브쿼리 표현식 설명](https://www.postgresql.org/docs/18/functions-subquery.html#FUNCTIONS-SUBQUERY-EXISTS)에서 확인할 수 있다.

| 목적 | 적합한 표현 | 결과의 한 행이 나타내는 것 |
| --- | --- | --- |
| 학생과 수강 강좌를 함께 표시한다. | `JOIN` | 학생·수강 강좌의 조합 |
| 수강 정보가 있는 학생을 선택한다. | `WHERE EXISTS` | 조건을 만족하는 학생 |
| 수강 정보가 없는 학생을 선택한다. | `WHERE NOT EXISTS` | 조건을 만족하는 학생 |

`EXISTS`가 어떤 결과에서든 중복을 제거하는 것은 아니다. **안쪽 행의 수 때문에 바깥 행이 늘어나는 일을 만들지 않는다.** 바깥 쿼리 자체에 다른 조인으로 생긴 중복이 있다면 그것까지 제거하지는 않는다.

## 정렬과 페이지 범위 지정하기

### `ORDER BY`로 결과 순서 정하기

정렬(Sorting)은 `ORDER BY`로 지정한다. 오름차순(Ascending Order, `ASC`)은 작은 값부터, 내림차순(Descending Order, `DESC`)은 큰 값부터 정렬한다. 방향을 생략하면 `ASC`다.

```sql
SELECT id, title, created_at
FROM courses
ORDER BY created_at DESC, id DESC;
```

먼저 생성 시각 `created_at`을 내림차순으로 비교하고, 시각이 같으면 ID를 내림차순으로 비교한다.

| 순서 | id | title | created_at |
| --- | --- | --- | --- |
| 1 | 30 | 운영체제 | 2026-09-29 09:00:00 |
| 2 | 20 | 네트워크 | 2026-09-28 09:00:00 |
| 3 | 10 | 데이터베이스 | 2026-09-28 09:00:00 |

`created_at DESC`만 지정하면 네트워크와 데이터베이스 중 무엇이 먼저인지 결정되지 않는다. 고유한 ID를 추가 기준으로 사용하면 같은 시각의 행도 서로 순서를 정할 수 있다. `ORDER BY`를 생략한 조회에는 반환 순서 보장이 없다. [PostgreSQL의 정렬 설명](https://www.postgresql.org/docs/18/queries-order.html)

### `LIMIT`·`OFFSET`으로 일부 행 조회하기

페이지네이션(Pagination)은 조회 결과를 나누어 가져오는 방식이다. 오프셋 기반 페이지네이션(Offset-Based Pagination)에서는 앞의 행을 건너뛰고, 그다음 일정 수의 행을 가져온다.

```sql
SELECT id, title
FROM courses
ORDER BY created_at DESC, id DESC
LIMIT 2 OFFSET 1;
```

| 지정 값 | 의미 |
| --- | --- |
| `OFFSET 1` | 정렬된 결과의 앞에서 한 행을 건너뛴다. |
| `LIMIT 2` | 그다음 최대 두 행을 반환한다. |

운영체제를 건너뛰므로 결과는 네트워크, 데이터베이스 순이다. SQL에는 `LIMIT`을 먼저 적었지만, 의미는 **앞의 행을 건너뛴 뒤 최대 지정 개수를 가져오는 것**이다. `LIMIT 2 OFFSET 2`라면 데이터베이스 한 행만 남는다. `LIMIT`은 반환 개수의 상한이므로 남은 행보다 많은 수를 지정해도 행을 채워 만들지 않는다.

페이지 사이에서 행이 겹치거나 빠지는 일을 살펴볼 때는 두 상황을 구분해야 한다.

| 상황 | 페이지 결과를 이해하는 기준 |
| --- | --- |
| 조회 대상과 정렬값이 변하지 않음 | 동률까지 결정하는 정렬 기준을 사용하면 같은 순서에서 각 페이지의 범위를 선택할 수 있다. |
| 조회 사이에 행이 추가·삭제되거나 정렬값이 바뀜 | 행의 위치가 이동할 수 있다. 앞서 사용한 offset이 다음 요청에서 같은 위치의 대상을 가리킨다고 보장할 수 없다. |

예를 들어 한 행씩 조회해 첫 페이지에서 운영체제를 받았다고 하자. 다음 요청 전에 더 최신인 강좌가 추가되면 운영체제가 두 번째 위치로 이동한다. 그때 `OFFSET 1`로 조회하면 운영체제가 다시 나올 수 있다. **정렬 기준을 분명히 정하는 것과 여러 요청에서 동일한 데이터를 보는 것은 별개의 문제다.** `LIMIT`·`OFFSET`과 정렬의 관계는 [PostgreSQL의 페이지 범위 설명](https://www.postgresql.org/docs/18/queries-limit.html), 조회 시점의 데이터는 [트랜잭션의 격리와 가시성](011-transaction-atomicity-and-concurrency.md#격리와-가시성-다른-트랜잭션에는-무엇이-보이는가)에서 확인할 수 있다.

## 프로젝트에서 적용한 사례

이제 앞의 SQL 개념을 게시글 조회에 적용한다. 아래 SQL은 의미를 읽기 위한 표현이며, 전체 API 응답을 구성하는 모든 조회를 나타내지는 않는다. `:viewer_id` 같은 표시는 값을 바인딩(Binding)할 매개변수(Parameter)다. 여기서는 SQLAlchemy의 이름 있는 매개변수(Named Parameter) 표기법을 사용한다.

### 팔로우한 작성자의 게시글 선택

피드에서는 조회자가 팔로우한 작성자의 게시글을 선택한다.

```sql
SELECT a.*
FROM articles AS a
WHERE EXISTS (
    SELECT uf.followed_id
    FROM user_follows AS uf
    WHERE uf.follower_id = :viewer_id
      AND uf.followed_id = a.author_id
);
```

바깥 쿼리의 대상은 게시글이다. 안쪽에서는 **조회자가 현재 게시글의 작성자를 팔로우하는지** 확인한다. 그 팔로우가 있으면 해당 게시글을 유지한다.

[`get_article_feed()`](../../app/articles/router.py)의 SQLAlchemy 표현은 다음과 같다.

```python
query = select(Article).where(
    select(UserFollow.followed_id)
    .where(
        UserFollow.follower_id == viewer.id,
        UserFollow.followed_id == Article.author_id,
    )
    .exists()
)
```

| SQLAlchemy 표현 | SQL에서의 역할 |
| --- | --- |
| `select(Article)` | 바깥에서 게시글을 선택한다. |
| `select(UserFollow.followed_id)` | 안쪽에서 팔로우 정보를 조회한다. |
| `UserFollow.follower_id == viewer.id` | 팔로우한 사용자를 조회자로 제한한다. |
| `UserFollow.followed_id == Article.author_id` | 안쪽 팔로우와 바깥 게시글의 작성자를 연결한다. |
| `.exists()` | 안쪽 조회를 존재 여부 조건으로 사용한다. |

이 코드는 조회 문을 구성한다. 이 시점에 팔로우 정보를 먼저 DB에서 가져오는 것이 아니다. 구성한 쿼리는 [`_article_list_response()`](../../app/articles/router.py)에서 실행된다. SQLAlchemy의 [조회 문 구성](https://docs.sqlalchemy.org/en/20/tutorial/data_select.html#the-select-sql-expression-construct)과 [EXISTS 표현](https://docs.sqlalchemy.org/en/20/tutorial/data_select.html#exists-subqueries)을 참고할 수 있다. 요청 전체의 흐름은 [게시글 피드 조회 흐름](../architecture/flows/article-feed.md)에 있다.

### 태그 조건: 안쪽에서는 조인하고 바깥에서는 존재 확인하기

태그 이름이 지정한 값과 같은 게시글을 선택한다.

```sql
SELECT a.*
FROM articles AS a
WHERE EXISTS (
    SELECT at.article_id
    FROM article_tags AS at
    INNER JOIN tags AS t ON t.id = at.tag_id
    WHERE at.article_id = a.id
      AND t.name = :tag_name
);
```

안쪽의 `JOIN`은 게시글·태그 연결에서 태그 이름을 확인하기 위해 사용한다. 바깥의 `EXISTS`는 조건에 맞는 태그 연결이 있는지만 판단한다. **`JOIN`과 `EXISTS`는 서로 대체해야 하는 문법이 아니라, 목적에 따라 함께 사용할 수 있는 표현**이다.

실제 표현은 [`list_articles()`](../../app/articles/router.py)의 `tag` 조건에서 확인할 수 있다.

### 즐겨찾기 조건: 검색 대상 사용자 확인하기

지정한 이름의 사용자가 즐겨찾기한 게시글을 선택한다.

```sql
SELECT a.*
FROM articles AS a
WHERE EXISTS (
    SELECT af.article_id
    FROM article_favorites AS af
    INNER JOIN users AS u ON u.id = af.user_id
    WHERE af.article_id = a.id
      AND u.username = :favorited_username
);
```

안쪽의 `users`는 **즐겨찾기를 등록한 사용자의 이름**을 확인하기 위해 연결한다. 이 쿼리에는 그 이름과 요청자의 이름을 비교하는 조건이 없다. D가 `favorited=C`로 요청하면 C가 즐겨찾기한 게시글을 선택한다.

선택된 게시글의 응답에 표시할 `favorited`는 별도로 조회자 D를 기준으로 계산한다. 검색 조건과 응답 상태는 서로 다른 질문에 답한다. 실제 검색 조건은 [`list_articles()`](../../app/articles/router.py), 응답 상태는 같은 파일의 `_article_list_response()`와 [`favorite_state()`](../../app/articles/favorites.py)에서 확인할 수 있다. 전체 요청 흐름은 [게시글 목록 조회 흐름](../architecture/flows/article-list.md)에 있다.

## 기억할 내용

- `FROM`은 데이터의 출처, `WHERE`는 행 선택 조건, `SELECT`는 결과에 표시할 열과 표현식을 정한다.
- `JOIN`을 사용하면 하나의 원래 행에 여러 행이 연결될 수 있다. 결과의 한 행이 어떤 대상을 나타내는지 확인한다.
- 서브쿼리는 값 하나, 여러 값과의 비교, 조회 대상 테이블 등 사용 위치에 따라 필요한 결과 형태가 다르다.
- 상관 서브쿼리는 바깥 행의 값을 안쪽 조건에서 참조한다. 이를 Python의 반복 DB 호출로 해석하지 않는다.
- `EXISTS`는 행의 존재 여부만 조건으로 사용한다. 안쪽 행 수만큼 바깥 행을 늘리거나, 바깥 쿼리의 기존 중복을 제거하지 않는다.
- 페이지 조회에는 동률까지 결정하는 정렬 기준이 필요하다. 조회 사이의 데이터 변경은 별도로 고려한다.
