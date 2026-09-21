from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, errors: dict[str, list[str]]) -> None:
        super().__init__(errors)
        self.status_code = status_code
        self.errors = errors


def api_error_handler(_request: Request, exception: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exception.status_code,
        content={"errors": exception.errors},
    )


def validation_error_handler(
    _request: Request,
    exception: RequestValidationError,
) -> JSONResponse:
    errors: defaultdict[str, list[str]] = defaultdict(list)

    for error in exception.errors():
        field = _validation_error_field(error.get("loc", ()))
        errors[field].append(str(error["msg"]))

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"errors": dict(errors)},
    )


def _validation_error_field(location: Sequence[Any]) -> str:
    if not location:
        return "body"
    return str(location[-1])
