from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import structlog
from fastapi import Depends, FastAPI, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from spendledger.config import Settings, get_settings
from spendledger.console import get_console_overview
from spendledger.database import Base, SessionFactory, build_engine, build_session_factory
from spendledger.errors import (
    AuthenticationError,
    ConflictError,
    ServiceError,
)
from spendledger.idempotency import (
    canonical_hash,
    find_record,
    store_record,
    validate_replay,
)
from spendledger.ledger import get_journal_response
from spendledger.observability import (
    CARD_EVENTS,
    RECONCILIATION_ITEMS,
    RequestContextMiddleware,
    configure_logging,
    metrics_payload,
    request_id_context,
)
from spendledger.reconciliation import get_reconciliation, reconcile
from spendledger.schemas import (
    CardEventCommand,
    ConsoleOverviewResponse,
    JournalResponse,
    ProblemDetails,
    ReconciliationRequest,
    ReconciliationResponse,
    TransactionResponse,
)
from spendledger.security import Principal, authenticate_api_key
from spendledger.transactions import get_transaction, process_card_event

logger = structlog.get_logger(__name__)


async def session_dependency(request: Request) -> AsyncIterator[AsyncSession]:
    factory: SessionFactory = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


SessionDependency = Annotated[AsyncSession, Depends(session_dependency)]


async def principal_dependency(
    session: SessionDependency,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    return await authenticate_api_key(session, _bearer_token(authorization))


PrincipalDependency = Annotated[Principal, Depends(principal_dependency)]


def _problem_response(
    *,
    status_code: int,
    code: str,
    detail: str,
    metadata: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ProblemDetails(
        type=f"https://spendledger.dev/problems/{code}",
        title=code.replace("_", " ").title(),
        status=status_code,
        detail=detail,
        code=code,
        request_id=request_id_context.get(),
        metadata=metadata or {},
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthenticationError()
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        raise AuthenticationError("Authorization must use a Bearer API key.")
    return value.strip()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(resolved_settings)
        factory = build_session_factory(engine)
        app.state.engine = engine
        app.state.session_factory = factory
        app.state.settings = resolved_settings
        if resolved_settings.auto_create_schema:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        yield
        await engine.dispose()

    app = FastAPI(
        title="SpendLedger",
        version="0.1.0",
        description=(
            "A reliable card-spend ledger and reconciliation service demonstrating "
            "idempotency, double-entry accounting, transactional outbox, and observability."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )

    @app.exception_handler(ServiceError)
    async def handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return _problem_response(
            status_code=exc.status_code,
            code=exc.code,
            detail=exc.detail,
            metadata=exc.metadata,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _problem_response(
            status_code=422,
            code="request_validation_failed",
            detail="The request payload or parameters are invalid.",
            metadata={"errors": jsonable_encoder(exc.errors())},
        )

    @app.get("/health/live", tags=["Operations"])
    async def health_live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", tags=["Operations"])
    async def health_ready(session: SessionDependency) -> JSONResponse:
        try:
            await session.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning("readiness_failed", dependency="database", error=str(exc))
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "database": "unavailable"},
            )
        return JSONResponse(content={"status": "ready", "database": "available"})

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=metrics_payload(), media_type="text/plain; version=0.0.4")

    @app.get(
        "/v1/console/overview",
        response_model=ConsoleOverviewResponse,
        tags=["Operations Console"],
    )
    async def console_overview(
        session: SessionDependency,
        principal: PrincipalDependency,
    ) -> ConsoleOverviewResponse:
        principal.require("spend:read")
        return await get_console_overview(
            session,
            tenant_id=principal.tenant_id,
        )

    @app.post(
        "/v1/card-events",
        response_model=TransactionResponse,
        status_code=201,
        tags=["Card Spend"],
    )
    async def ingest_card_event(
        command: CardEventCommand,
        session: SessionDependency,
        principal: PrincipalDependency,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8)],
    ) -> JSONResponse:
        principal.require("spend:write")
        endpoint = "POST:/v1/card-events"
        request_hash = canonical_hash(command.model_dump(mode="json"))
        existing = await find_record(
            session,
            tenant_id=principal.tenant_id,
            endpoint=endpoint,
            key=idempotency_key,
        )
        if existing is not None:
            validate_replay(existing, request_hash)
            CARD_EVENTS.labels(
                event_type=command.event_type.value, result="idempotent_replay"
            ).inc()
            return JSONResponse(
                status_code=existing.response_status,
                content=existing.response_body,
                headers={"Idempotent-Replayed": "true"},
            )

        try:
            transaction, processor_replay = await process_card_event(
                session,
                tenant_id=principal.tenant_id,
                actor=principal.api_key_name,
                command=command,
            )
            body = TransactionResponse.model_validate(transaction).model_dump(mode="json")
            store_record(
                session,
                tenant_id=principal.tenant_id,
                endpoint=endpoint,
                key=idempotency_key,
                request_hash=request_hash,
                response_status=201,
                response_body=body,
            )
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            concurrent = await find_record(
                session,
                tenant_id=principal.tenant_id,
                endpoint=endpoint,
                key=idempotency_key,
            )
            if concurrent is None:
                raise ConflictError(
                    "concurrent_event_conflict",
                    "A concurrent request created the same processor event.",
                ) from exc
            validate_replay(concurrent, request_hash)
            return JSONResponse(
                status_code=concurrent.response_status,
                content=concurrent.response_body,
                headers={"Idempotent-Replayed": "true"},
            )

        CARD_EVENTS.labels(
            event_type=command.event_type.value,
            result="processor_replay" if processor_replay else "processed",
        ).inc()
        return JSONResponse(
            status_code=201,
            content=body,
            headers={"Idempotent-Replayed": str(processor_replay).lower()},
        )

    @app.get(
        "/v1/transactions/{external_transaction_id}",
        response_model=TransactionResponse,
        tags=["Card Spend"],
    )
    async def read_transaction(
        external_transaction_id: str,
        session: SessionDependency,
        principal: PrincipalDependency,
    ) -> TransactionResponse:
        principal.require("spend:read")
        transaction = await get_transaction(
            session,
            tenant_id=principal.tenant_id,
            external_transaction_id=external_transaction_id,
        )
        return TransactionResponse.model_validate(transaction)

    @app.get(
        "/v1/journals/{reference:path}",
        response_model=JournalResponse,
        tags=["Accounting"],
    )
    async def read_journal(
        reference: str,
        session: SessionDependency,
        principal: PrincipalDependency,
    ) -> JournalResponse:
        principal.require("ledger:read")
        return await get_journal_response(
            session,
            tenant_id=principal.tenant_id,
            reference=reference,
        )

    @app.post(
        "/v1/reconciliations",
        response_model=ReconciliationResponse,
        status_code=201,
        tags=["Reconciliation"],
    )
    async def create_reconciliation(
        payload: ReconciliationRequest,
        session: SessionDependency,
        principal: PrincipalDependency,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8)],
    ) -> JSONResponse:
        principal.require("reconciliation:write")
        endpoint = "POST:/v1/reconciliations"
        request_hash = canonical_hash(payload.model_dump(mode="json"))
        existing = await find_record(
            session,
            tenant_id=principal.tenant_id,
            endpoint=endpoint,
            key=idempotency_key,
        )
        if existing is not None:
            validate_replay(existing, request_hash)
            return JSONResponse(
                status_code=existing.response_status,
                content=existing.response_body,
                headers={"Idempotent-Replayed": "true"},
            )
        try:
            result = await reconcile(
                session,
                tenant_id=principal.tenant_id,
                actor=principal.api_key_name,
                request=payload,
            )
            body = result.model_dump(mode="json")
            store_record(
                session,
                tenant_id=principal.tenant_id,
                endpoint=endpoint,
                key=idempotency_key,
                request_hash=request_hash,
                response_status=201,
                response_body=body,
            )
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            concurrent = await find_record(
                session,
                tenant_id=principal.tenant_id,
                endpoint=endpoint,
                key=idempotency_key,
            )
            if concurrent is None:
                raise ConflictError(
                    "concurrent_reconciliation_conflict",
                    "A concurrent reconciliation request conflicted with this request.",
                ) from exc
            validate_replay(concurrent, request_hash)
            return JSONResponse(
                status_code=concurrent.response_status,
                content=concurrent.response_body,
                headers={"Idempotent-Replayed": "true"},
            )

        for item in result.items:
            RECONCILIATION_ITEMS.labels(status=item.status.value).inc()
        return JSONResponse(status_code=201, content=body)

    @app.get(
        "/v1/reconciliations/{run_id}",
        response_model=ReconciliationResponse,
        tags=["Reconciliation"],
    )
    async def read_reconciliation(
        run_id: str,
        session: SessionDependency,
        principal: PrincipalDependency,
    ) -> ReconciliationResponse:
        principal.require("reconciliation:read")
        return await get_reconciliation(
            session,
            tenant_id=principal.tenant_id,
            run_id=run_id,
        )

    return app
