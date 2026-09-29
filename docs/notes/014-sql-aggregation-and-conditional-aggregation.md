# SQL 집계와 조건부 집계

이 노트는 SQL(Structured Query Language)로 여러 행의 개수·합계·평균을 계산하고, 집계 대상에 조건을 적용하는 방법을 설명한다. 상품별 주문 내역으로 기본 원리를 살펴본 뒤, 프로젝트의 즐겨찾기 상태와 게시글 개수 계산에 연결한다. 조회 문과 서브쿼리의 기본 구조는 [SQL 조회와 서브쿼리](013-sql-queries-and-subqueries.md)에서 다룬다.

## 집계란 무엇인가

집계(Aggregation)는 여러 행(Row)의 값을 하나의 결과로 요약하는 연산이다. 집계 함수(Aggregate Function)는 개수, 합계, 평균처럼 요약할 값의 계산 방법을 정한다.

다음 주문 품목(Order Item) 테이블 `order_items`를 공통 예제로 사용한다. **한 행은 한 주문에 포함된 상품 한 종류**다. 주문 101에는 키보드와 마우스가 있어 두 행으로 표현된다. 이 예제에서는 상품명으로 상품 종류를 구분한다.

| id | order_id | product | quantity | amount | discount_amount | status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 101 | 키보드 | 2 | 100000 | 10000 | paid |
| 2 | 101 | 마우스 | 1 | 30000 | NULL | paid |
| 3 | 102 | 키보드 | 1 | 50000 | 0 | paid |
| 4 | 103 | 마우스 | 2 | 60000 | 5000 | cancelled |
| 5 | 104 | 모니터 | 1 | 200000 | NULL | pending |

- `quantity`는 해당 품목의 수량이다. 한 행이 상품 한 개를 뜻하지는 않는다.
- `amount`는 수량을 반영한 **할인 전 품목 금액**이며, 금액의 단위는 원이다.
- `discount_amount`는 품목의 할인 금액이다. 널(NULL)은 금액이 기록되지 않았다는 의미이고, `0`은 할인 금액이 0원으로 기록됐다는 의미다.
- `status`는 주문 상태다. `paid`는 결제 완료, `cancelled`는 취소, `pending`은 결제 대기를 뜻한다.

전체 주문 품목이 몇 행인지 조회한다.

```sql
SELECT COUNT(*) AS item_count
FROM order_items;
```

| item_count |
| --- |
| 5 |

원본 데이터는 다섯 행이지만, 집계 결과는 **전체 품목 수를 나타내는 한 행**이다. `AS item_count`는 결과 열(Column)에 별칭(Column Alias)을 붙인다. 집계 함수 여러 개를 함께 선택하면 한 결과 행에 여러 요약 값을 담을 수 있다.

## `COUNT`로 개수 세기

### 행·값·서로 다른 값의 개수 구분하기

`COUNT`는 무엇을 인수(Argument)로 지정하는지에 따라 세는 대상이 달라진다.

```sql
SELECT
    COUNT(*) AS item_count,
    COUNT(discount_amount) AS recorded_discount_count,
    COUNT(DISTINCT product) AS product_count,
    COUNT(DISTINCT order_id) AS order_count
FROM order_items;
```

| item_count | recorded_discount_count | product_count | order_count |
| --- | --- | --- | --- |
| 5 | 3 | 3 | 4 |

| 표현 | 세는 대상 | 예제에서의 계산 |
| --- | --- | --- |
| `COUNT(*)` | 입력 행 전체 | 주문 품목 다섯 행 |
| `COUNT(discount_amount)` | 해당 값이 `NULL`이 아닌 행 | 할인 금액이 기록된 세 행. `0`도 포함한다. |
| `COUNT(DISTINCT product)` | `NULL`을 제외한 서로 다른 상품명 | 키보드·마우스·모니터 세 종류 |
| `COUNT(DISTINCT order_id)` | `NULL`을 제외한 서로 다른 주문 ID | 101·102·103·104의 네 주문 |

`DISTINCT`는 중복된 값을 제거한 뒤 계산하게 한다. 여기서 주문 품목 수와 주문 수가 다른 이유는 주문 하나에 여러 품목이 있기 때문이다. **개수를 요구받으면 먼저 무엇 하나를 한 건으로 셀지 정해야 한다.**

`COUNT(*)`는 입력 행의 값을 보고 같은 대상을 자동으로 합치지 않는다. 조인(Join)으로 한 대상이 여러 결과 행에 나타났다면 그 행들을 모두 센다. 조인에 따른 행의 변화는 [SQL 조회와 서브쿼리](013-sql-queries-and-subqueries.md#join으로-테이블-연결하기)에서 확인할 수 있다.

### `NULL`과 0은 다른 값이다

`COUNT(discount_amount)`는 값의 크기를 더하는 연산이 아니다. `10000`, `0`, `5000` 각각이 기록된 값 하나이므로 결과는 `3`이다. `COUNT(*)`는 할인 금액이 `NULL`인 행도 포함해 `5`를 반환한다.

집계 표현식(Aggregate Expression)의 `DISTINCT`와 `NULL` 처리 규칙은 [PostgreSQL의 집계 표현식 설명](https://www.postgresql.org/docs/18/sql-expressions.html#SYNTAX-AGGREGATES)에서 확인할 수 있다.

## 합계·평균·최솟값·최댓값 구하기

### 각 함수가 요약하는 값

| 함수 | 의미 | 예제에서 확인할 값 |
| --- | --- | --- |
| `SUM` | 합계(Sum) | 품목 수량 또는 금액의 합 |
| `AVG` | 산술 평균(Arithmetic Mean) | 기록된 품목 금액의 평균 |
| `MIN` | 최솟값(Minimum) | 가장 작은 품목 금액 |
| `MAX` | 최댓값(Maximum) | 가장 큰 품목 금액 |

모든 주문 상태를 포함해 품목의 수량과 금액을 집계한다.

```sql
SELECT
    SUM(quantity) AS total_quantity,
    SUM(amount) AS total_amount,
    AVG(amount) AS average_amount,
    MIN(amount) AS minimum_amount,
    MAX(amount) AS maximum_amount
FROM order_items;
```

| total_quantity | total_amount | average_amount | minimum_amount | maximum_amount |
| --- | --- | --- | --- | --- |
| 7 | 440000 | 88000 | 30000 | 200000 |

품목은 다섯 행이지만 수량 합계는 `2 + 1 + 1 + 2 + 1 = 7`이다. 평균 금액은 다섯 품목의 금액 합계 `440000`을 다섯 행으로 나눈 `88000`이다. **상품 한 개당 평균 가격**을 구한 것은 아니다. 어떤 값의 평균인지 결과 이름과 계산 대상을 함께 확인한다.

### `NULL`은 평균의 분모에도 포함되지 않는다

이 노트에서 다루는 `SUM`·`AVG`·`MIN`·`MAX`는 `NULL`이 아닌 입력 값으로 계산한다.

```sql
SELECT
    COUNT(discount_amount) AS recorded_discount_count,
    SUM(discount_amount) AS total_discount,
    AVG(discount_amount) AS average_discount
FROM order_items;
```

| recorded_discount_count | total_discount | average_discount |
| --- | --- | --- |
| 3 | 15000 | 5000 |

평균은 기록된 세 값 `10000`, `0`, `5000`으로 계산하므로 `15000 / 3 = 5000`이다. `NULL`을 0으로 간주해 다섯 행으로 나누는 계산과는 다르다. 기록되지 않은 값을 0으로 볼지는 별도의 데이터 해석 규칙이다.

### 집계할 값이 없는 경우

예제에는 환불 상태 `refunded`인 품목이 없다.

```sql
SELECT
    COUNT(*) AS item_count,
    SUM(amount) AS total_amount,
    AVG(amount) AS average_amount,
    MIN(amount) AS minimum_amount,
    MAX(amount) AS maximum_amount
FROM order_items
WHERE status = 'refunded';
```

| item_count | total_amount | average_amount | minimum_amount | maximum_amount |
| --- | --- | --- | --- | --- |
| 0 | NULL | NULL | NULL | NULL |

이 형태는 그룹화 없이 전체를 집계하므로 입력 행이 없어도 결과 한 행을 반환한다. `COUNT`는 `0`, 나머지 네 함수는 `NULL`이다. `SUM`을 자동으로 0이라고 가정하면 안 된다. 함수의 정의와 빈 입력 결과는 [PostgreSQL의 집계 함수 설명](https://www.postgresql.org/docs/18/functions-aggregate.html)을 참고할 수 있다.

입력 행은 있지만 특정 열의 값이 모두 `NULL`인 경우도 구분한다. 모니터 품목은 존재하지만 할인 금액이 기록되지 않았다. 모니터만 대상으로 `COUNT(*)`를 계산하면 `1`, `COUNT(discount_amount)`는 `0`, `SUM(discount_amount)`는 `NULL`이다.

## `GROUP BY`로 그룹별 집계하기

그룹화(Grouping)는 지정한 열이나 표현식의 값이 같은 행들을 묶는 것이다. `GROUP BY product`는 상품명이 같은 품목끼리 묶고, 각 그룹(Group) 안에서 집계한다.

```sql
SELECT
    product,
    COUNT(*) AS item_count,
    SUM(quantity) AS total_quantity,
    SUM(amount) AS total_amount
FROM order_items
GROUP BY product;
```

| product | item_count | total_quantity | total_amount |
| --- | --- | --- | --- |
| 키보드 | 2 | 3 | 150000 |
| 마우스 | 2 | 3 | 90000 |
| 모니터 | 1 | 1 | 200000 |

이 결과의 **한 행은 상품 하나의 집계 결과**다. 키보드 그룹은 원본의 ID 1·3, 마우스 그룹은 ID 2·4, 모니터 그룹은 ID 5로 계산한다. 결과표의 행 순서는 설명용이며, `GROUP BY` 자체는 정렬을 보장하지 않는다. 순서가 필요하면 `ORDER BY`를 지정한다.

| 조회 형태 | 집계 범위 | 결과 행의 의미 |
| --- | --- | --- |
| `SELECT COUNT(*) FROM order_items` | 입력 행 전체 | 전체 개수 한 행 |
| `SELECT product, COUNT(*) ... GROUP BY product` | 상품별 입력 행 | 상품별 개수 한 행씩 |

상품명과 상태를 함께 그룹 기준으로 지정하면 한 상품도 상태에 따라 여러 그룹으로 나뉜다. 그룹 기준은 결과를 어느 단위로 요약할지 정한다.

위 예시에서 `product`를 결과에 표시할 수 있는 이유는 그룹을 구분하는 값이기 때문이다. 반면 키보드 그룹에 원본 `id`가 1·3으로 여러 개 있는데, 어떤 ID인지 정하지 않고 결과에 표시할 수는 없다. 그룹 기준과 집계 값을 구분해야 한다.

입력이 없는 그룹별 집계도 살펴본다.

```sql
SELECT product, COUNT(*) AS item_count
FROM order_items
WHERE status = 'refunded'
GROUP BY product;
```

환불 품목이 없어 만들 상품 그룹도 없으므로 **결과는 0행**이다. 앞의 전체 집계가 `item_count = 0`인 한 행을 반환한 것과 다르다. 그룹화의 의미는 [PostgreSQL의 GROUP BY·HAVING 설명](https://www.postgresql.org/docs/18/queries-table-expressions.html#QUERIES-GROUP)을 참고할 수 있다.

## `WHERE`와 `HAVING`으로 대상 제한하기

`WHERE`는 집계할 원본 행을 선택하고, `HAVING`은 집계 결과의 그룹을 선택한다. **어떤 단계의 대상을 제한하는지**가 다르다.

결제 완료 품목을 상품별로 집계하고, 그 품목이 두 행 이상인 상품만 조회한다.

```sql
SELECT
    product,
    COUNT(*) AS item_count,
    SUM(quantity) AS total_quantity
FROM order_items
WHERE status = 'paid'
GROUP BY product
HAVING COUNT(*) >= 2;
```

| 단계 | 조건·연산 | 남는 대상 |
| --- | --- | --- |
| 원본 행 선택 | `WHERE status = 'paid'` | ID 1·2·3의 세 품목 |
| 그룹별 집계 | `GROUP BY product` | 키보드: 품목 2행·수량 3개, 마우스: 품목 1행·수량 1개 |
| 그룹 선택 | `HAVING COUNT(*) >= 2` | 품목이 두 행인 키보드 그룹 |

최종 결과는 다음과 같다.

| product | item_count | total_quantity |
| --- | --- | --- |
| 키보드 | 2 | 3 |

`WHERE COUNT(*) >= 2`로 옮겨 적을 수는 없다. 같은 쿼리 수준에서 `WHERE`가 행을 선택할 때는 그 행들로 계산할 집계 결과가 아직 정해지지 않았기 때문이다. 집계 값을 조건으로 그룹을 선택할 때 `HAVING`을 사용한다. [PostgreSQL의 집계 입문 설명](https://www.postgresql.org/docs/18/tutorial-agg.html)

이 표는 쿼리 결과를 이해하는 논리적 처리 순서(Logical Processing Order)다. 데이터베이스가 반드시 표의 순서대로 물리적인 작업을 수행한다는 의미는 아니다.

## `FILTER`로 조건부 집계하기

조건부 집계(Conditional Aggregation)는 특정 조건을 만족하는 행만 집계 함수의 입력으로 사용하는 것이다. `FILTER (WHERE 조건)`은 **바로 앞에 있는 집계 함수 하나**에 적용된다.

전체 품목 수와 상태별 품목 수, 결제 완료 금액을 한 번의 조회에서 계산한다.

```sql
SELECT
    COUNT(*) AS all_item_count,
    COUNT(*) FILTER (WHERE status = 'paid') AS paid_item_count,
    COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_item_count,
    COUNT(*) FILTER (WHERE status = 'pending') AS pending_item_count,
    SUM(amount) FILTER (WHERE status = 'paid') AS paid_amount
FROM order_items;
```

| all_item_count | paid_item_count | cancelled_item_count | pending_item_count | paid_amount |
| --- | --- | --- | --- | --- |
| 5 | 3 | 1 | 1 | 180000 |

첫 번째 `COUNT(*)`에는 모든 품목이 입력된다. `paid_item_count`는 결제 완료인 세 행만 세고, `paid_amount`는 그 세 행의 금액 `100000 + 30000 + 50000`을 더한다. 여러 집계 함수가 있어도 그룹화 없는 이 조회의 결과는 **여러 열을 가진 한 행**이다.

### `WHERE`와 `FILTER`의 차이

다음 쿼리는 집계 전에 원본 행을 결제 완료로 제한한다.

```sql
SELECT
    COUNT(*) AS item_count,
    COUNT(*) FILTER (WHERE status = 'paid') AS paid_item_count,
    COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled_item_count
FROM order_items
WHERE status = 'paid';
```

| item_count | paid_item_count | cancelled_item_count |
| --- | --- | --- |
| 3 | 3 | 0 |

취소 품목은 이미 `WHERE`에서 제외됐으므로, 취소 상태의 `FILTER`를 붙여도 다시 집계할 수 없다. **`FILTER`는 쿼리의 공통 입력 안에서 각 함수에 사용할 행을 고른다.**

| 조건의 위치 | 제한하는 대상 |
| --- | --- |
| `WHERE` | 모든 집계 함수가 사용할 공통 원본 행 |
| 집계 함수의 `FILTER` | 해당 집계 함수에 입력할 행 |
| `HAVING` | 집계 후 결과에 포함할 그룹 |

`FILTER`는 `GROUP BY`와 함께 사용할 수도 있다. 그때는 각 그룹 안에서 조건에 맞는 행만 해당 함수에 입력한다. `COUNT`의 조건에 맞는 행이 없으면 `0`이고, `SUM`에 입력할 값이 없으면 `NULL`이라는 규칙도 유지된다. [PostgreSQL의 FILTER 설명](https://www.postgresql.org/docs/18/sql-expressions.html#SYNTAX-AGGREGATES)

## 프로젝트에서 적용한 사례

### 게시글의 전체 즐겨찾기 수와 조회자 상태

사용자 A·C가 게시글 X를 즐겨찾기하고, D는 즐겨찾기하지 않았다고 하자. A·C·D의 ID는 각각 1·3·4, X의 ID는 10으로 가정한다.

| user_id | article_id |
| --- | --- |
| 1 | 10 |
| 3 | 10 |

아래 SQL은 X의 전체 즐겨찾기 수와 조회자의 즐겨찾기 수를 함께 계산한다. `:article_id`·`:viewer_id`는 SQLAlchemy의 이름 있는 매개변수(Named Parameter) 표기이며, 실행할 값을 바인딩(Binding)하는 위치다.

```sql
SELECT
    COUNT(*) AS favorites_count,
    COUNT(*) FILTER (WHERE user_id = :viewer_id) AS viewer_count
FROM article_favorites
WHERE article_id = :article_id;
```

`article_id = 10`, `viewer_id = 1`일 때 결과는 다음과 같다.

| favorites_count | viewer_count |
| --- | --- |
| 2 | 1 |

`WHERE`는 두 집계의 공통 대상을 X의 즐겨찾기로 제한한다. 첫 번째 집계는 A·C를 모두 세고, 두 번째 집계의 `FILTER`는 조회자 A만 센다. **조회자 조건 때문에 첫 번째 개수에서 C가 제외되는 것은 아니다.**

[`favorite_state()`](../../app/articles/favorites.py)의 실제 표현은 다음과 같다.

```python
favorites_count, viewer_count = session.execute(
    select(
        func.count(),
        func.count().filter(ArticleFavorite.user_id == viewer_id),
    )
    .select_from(ArticleFavorite)
    .where(ArticleFavorite.article_id == article_id)
).one()
```

| SQLAlchemy 표현 | 역할 |
| --- | --- |
| `func.count()` | SQL의 `COUNT(*)`를 표현한다. |
| `.filter(...)` | 바로 앞 집계 함수의 `FILTER (WHERE ...)`를 표현한다. |
| `.select_from(ArticleFavorite)` | 즐겨찾기 테이블을 집계의 출처로 정한다. |
| `.where(...)` | 두 집계의 공통 대상을 해당 게시글로 제한한다. |
| `session.execute(...)` | 구성한 조회 문을 실행한다. |
| `.one()` | 결과가 정확히 한 행인지 확인하고 그 행을 가져온다. |

SQLAlchemy의 [COUNT 표현](https://docs.sqlalchemy.org/en/20/core/functions.html#sqlalchemy.sql.functions.count)과 [집계 FILTER 표현](https://docs.sqlalchemy.org/en/20/tutorial/data_select.html#special-modifiers-within-group-filter)을 참고할 수 있다.

`one()`은 즐겨찾기 원본 행 한 개를 가져온다는 뜻이 아니다. 위 조회의 **집계 결과 한 행에 있는 두 값**을 가져와 각각의 변수에 담는다. 결과가 0행이거나 여러 행이면 예외가 발생하며, SQL에 `LIMIT 1`을 붙이는 기능도 아니다. [SQLAlchemy의 Result.one 설명](https://docs.sqlalchemy.org/en/20/core/connections.html#sqlalchemy.engine.Result.one)

조회자가 D라면 결과는 `(2, 0)`이다. 함수는 `viewer_count > 0`으로 즐겨찾기 여부를 판단하므로, D의 `favorited`는 `false`, `favoritesCount`는 `2`다. X에 즐겨찾기가 하나도 없어도 이 조회는 `(0, 0)`인 한 행을 반환한다.

여기서 행의 수를 사용자 수로 해석할 수 있는 이유도 확인해야 한다. [`ArticleFavorite`](../../app/articles/models.py)는 `(user_id, article_id)`를 복합 기본 키(Composite Primary Key)로 사용한다. 같은 사용자가 같은 게시글에 중복 저장될 수 없으므로 X의 각 행이 서로 다른 사용자 한 명을 나타낸다. 이 제약이 없다면 `COUNT(*)`만으로 서로 다른 사용자 수를 보장할 수 없다.

### 페이지 범위 적용 전 전체 게시글 수 계산

목록 응답의 `articlesCount`는 검색 조건에 맞는 전체 게시글 수다. 특정 작성자의 게시글 개수를 세는 SQL로 표현하면 다음과 같다.

```sql
SELECT COUNT(*) AS articles_count
FROM (
    SELECT id
    FROM articles
    WHERE author_id = :author_id
) AS matched_articles;
```

서브쿼리(Subquery)는 조건에 맞는 게시글들을 집계 대상으로 제공한다. 여기에 `LIMIT`·`OFFSET`을 적용하지 않았으므로 현재 페이지의 개수로 제한되지 않는다.

[`_article_list_response()`](../../app/articles/router.py)는 이미 필터가 적용된 `query`로 전체 개수를 계산한다.

```python
total_count = session.scalar(select(func.count()).select_from(query.subquery()))
```

`query.subquery()`는 조회 문을 파생 테이블(Derived Table)로 사용하도록 표현한다. 바깥의 `func.count()`는 그 결과 행의 개수를 센다. `session.scalar()`는 조회를 실행해 첫 행의 첫 열 값을 반환하므로, 이 쿼리에서는 개수 숫자 하나를 가져온다. `scalar()` 자체가 결과를 정확히 한 행으로 제한하거나 행 수를 검사하는 것은 아니다. 이 집계 형태가 한 행을 반환한다. [SQLAlchemy의 Session.scalar 설명](https://docs.sqlalchemy.org/en/20/orm/session_api.html#sqlalchemy.orm.Session.scalar), [스칼라 결과 반환 규칙](https://docs.sqlalchemy.org/en/20/core/connections.html#sqlalchemy.engine.Result.scalar)

같은 함수에서 페이지의 게시글은 별도로 조회한다.

```python
articles = session.scalars(
    query.order_by(Article.created_at.desc(), Article.id.desc())
    .limit(limit)
    .offset(offset)
).all()
```

| 조건 | 전체 개수 집계 | 페이지 조회 |
| --- | --- | --- |
| 조건에 맞는 글 25개, `limit=10`, `offset=20` | `articlesCount = 25` | `articles`에 남은 글 5개 |
| 조건에 맞는 글 25개, `limit=10`, `offset=30` | `articlesCount = 25` | 빈 `articles` |
| 조건에 맞는 글 없음 | `articlesCount = 0` | 빈 `articles` |

`session.scalars(...).all()`은 이 조회에서 게시글 객체들을 가져온다. 이름이 비슷해도 개수 숫자 하나를 가져오는 `session.scalar()`와 역할이 다르다. 전체 개수와 페이지 응답의 흐름은 [게시글 목록 조회 흐름](../architecture/flows/article-list.md), 정렬과 페이지 범위의 원리는 [SQL 조회와 서브쿼리](013-sql-queries-and-subqueries.md#정렬과-페이지-범위-지정하기)에서 확인할 수 있다.

## 기억할 내용

- 집계 전에 입력의 한 행이 무엇을 나타내는지 확인한다. 품목 수, 주문 수, 수량 합계는 다른 값이다.
- `COUNT(*)`는 입력 행을 세고, `COUNT(column)`은 `NULL`이 아닌 값을 가진 행을 센다. `COUNT(DISTINCT column)`은 서로 다른 값의 수를 센다.
- `AVG`에서 `NULL`은 평균을 계산할 값의 개수에도 포함되지 않는다. `NULL`과 0은 구분한다.
- `GROUP BY`는 결과를 요약할 단위를 정한다. 전체 집계 한 행과 그룹별 집계의 여러 행을 구분한다.
- `WHERE`는 공통 원본 행, `FILTER`는 해당 함수의 입력 행, `HAVING`은 결과에 포함할 그룹을 제한한다.
- 입력이 없을 때 전체 집계의 `COUNT`는 0, `SUM`·`AVG`·`MIN`·`MAX`는 `NULL`이다. 만들 그룹이 없는 그룹별 집계는 결과가 0행이다.
- SQLAlchemy의 결과 반환 방법은 SQL이 만든 결과 형태에 맞춰 읽는다. `one()`이 가져오는 집계 결과 한 행을 원본 데이터 한 행과 혼동하지 않는다.
