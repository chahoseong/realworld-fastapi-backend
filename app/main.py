from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.articles.router import router as articles_router
from app.errors import ApiError, api_error_handler, validation_error_handler
from app.users.router import router as users_router

app = FastAPI(title="RealWorld FastAPI Backend")
app.exception_handler(RequestValidationError)(validation_error_handler)
app.exception_handler(ApiError)(api_error_handler)
app.include_router(users_router)
app.include_router(articles_router)
