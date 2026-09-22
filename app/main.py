from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.errors import ApiError, api_error_handler, validation_error_handler
from app.users.router import router as users_router

app = FastAPI(title="RealWorld FastAPI Backend")
app.exception_handler(RequestValidationError)(validation_error_handler)
app.exception_handler(ApiError)(api_error_handler)
app.include_router(users_router)
