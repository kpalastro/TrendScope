from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import Base, engine
from app.core.errors import ApiError, error_payload

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trendscope")

app = FastAPI(
    title="TrendScope AI",
    version="1.0.0-phase1",
    description=(
        "Australian eCommerce product intelligence. Synthetic demo data is labelled; "
        "growth is derived from relative search interest, not sales."
    ),
    docs_url="/api/docs",
    openapi_url="/api/v1/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:16]}"
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@app.on_event("startup")
def create_schema() -> None:
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)


def _respond(request: Request, status: int, code: str, message: str, details=None, headers=None):
    return JSONResponse(
        status_code=status,
        content=error_payload(code, message, details, request.state.request_id),
        headers=headers or {},
    )


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return _respond(request, exc.status_code, exc.code, exc.message, exc.details, exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    details = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", []) if part != "body"]
        details.append({"field": ".".join(location), "issue": error.get("msg", "invalid")})
    return _respond(request, 422, "VALIDATION_ERROR", "One or more fields are invalid.", details)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    code = {
        401: "UNAUTHENTICATED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
    }.get(exc.status_code, "HTTP_ERROR")
    return _respond(request, exc.status_code, code, str(exc.detail), headers=exc.headers)

@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return _respond(
        request,
        500,
        "INTERNAL_ERROR",
        "An unexpected error occurred. Quote the request id when reporting it.",
    )


app.include_router(api_router, prefix=settings.api_prefix)
app.include_router(health_router)
