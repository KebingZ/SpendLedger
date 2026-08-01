from __future__ import annotations

import logging
import sys
import time
from contextvars import ContextVar
from uuid import uuid4

import structlog
from prometheus_client import Counter, Histogram, generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from structlog.contextvars import bind_contextvars, unbind_contextvars

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

HTTP_REQUESTS = Counter(
    "spendledger_http_requests_total",
    "HTTP requests handled by SpendLedger.",
    ["method", "path", "status"],
)
HTTP_DURATION = Histogram(
    "spendledger_http_request_duration_seconds",
    "End-to-end HTTP request duration.",
    ["method", "path"],
)
CARD_EVENTS = Counter(
    "spendledger_card_events_total",
    "Card processor events by type and result.",
    ["event_type", "result"],
)
RECONCILIATION_ITEMS = Counter(
    "spendledger_reconciliation_items_total",
    "Reconciliation items by result.",
    ["status"],
)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def metrics_payload() -> bytes:
    return generate_latest()


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        incoming_id = headers.get(b"x-request-id", b"").decode("utf-8").strip()
        request_id = incoming_id[:100] if incoming_id else str(uuid4())
        token = request_id_context.set(request_id)
        bind_contextvars(request_id=request_id)
        method = str(scope.get("method", "UNKNOWN"))
        path = str(scope.get("path", "unknown"))
        status_code = 500
        started = time.monotonic()

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                mutable_headers = list(message.get("headers", []))
                mutable_headers.append((b"x-request-id", request_id.encode("utf-8")))
                message["headers"] = mutable_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        finally:
            route = scope.get("route")
            metric_path = str(getattr(route, "path", path))
            HTTP_REQUESTS.labels(method=method, path=metric_path, status=str(status_code)).inc()
            HTTP_DURATION.labels(method=method, path=metric_path).observe(
                time.monotonic() - started
            )
            unbind_contextvars("request_id")
            request_id_context.reset(token)
