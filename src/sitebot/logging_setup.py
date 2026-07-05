"""Structured logging: JSON output, request ids, optional Sentry.

Every log line carries the current request id (when inside a request) so a
single request can be traced across the API and error tracker.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from sitebot.config import Settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    # Uvicorn's access log is noisy and unstructured; our middleware logs requests.
    logging.getLogger("uvicorn.access").disabled = True

    if settings.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.05)
        except ImportError:
            logging.getLogger(__name__).warning(
                "SENTRY_DSN set but sentry-sdk is not installed; pip install sentry-sdk"
            )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, time the request, and emit one structured log line."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logging.getLogger("sitebot.request").exception(
                "unhandled error %s %s", request.method, request.url.path
            )
            raise
        finally:
            request_id_var.reset(token)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logging.getLogger("sitebot.request").info(
            "%s %s %s %.1fms", request.method, request.url.path,
            response.status_code, elapsed_ms,
        )
        response.headers["X-Request-ID"] = rid
        return response
