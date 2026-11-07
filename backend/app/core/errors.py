"""Typed API errors rendered through one envelope."""

from __future__ import annotations

from typing import Any

from fastapi import Request


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.headers = headers or {}


def error_payload(
    code: str, message: str, details: list[dict[str, Any]] | None = None, request_id: str | None = None
) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": request_id,
        }
    }


def request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)
