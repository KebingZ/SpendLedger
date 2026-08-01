from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from spendledger.api import create_app
from spendledger.config import Settings
from spendledger.database import SessionFactory
from spendledger.ledger import CARD_PAYABLE, EXPENSE_CLEARING
from spendledger.models import Account, AccountType, Tenant
from spendledger.security import create_api_key


@dataclass
class ApiFixture:
    client: httpx.AsyncClient
    api_key: str
    tenant_id: str
    session_factory: SessionFactory

    def headers(
        self,
        *,
        idempotency_key: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {api_key or self.api_key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers


async def seed_tenant(
    session: AsyncSession,
    *,
    settings: Settings,
    name: str,
    scopes: list[str] | None = None,
) -> tuple[Tenant, str]:
    tenant = Tenant(name=name)
    session.add(tenant)
    await session.flush()
    for currency in ("AUD", "USD"):
        session.add_all(
            [
                Account(
                    tenant_id=tenant.id,
                    code=EXPENSE_CLEARING,
                    name="Employee Expense Clearing",
                    account_type=AccountType.EXPENSE,
                    currency=currency,
                ),
                Account(
                    tenant_id=tenant.id,
                    code=CARD_PAYABLE,
                    name="Card Payable",
                    account_type=AccountType.LIABILITY,
                    currency=currency,
                ),
            ]
        )
    _, raw_key = await create_api_key(
        session,
        settings=settings,
        tenant_id=tenant.id,
        name="test-key",
        scopes=scopes
        or [
            "spend:write",
            "spend:read",
            "ledger:read",
            "reconciliation:write",
            "reconciliation:read",
        ],
    )
    await session.commit()
    return tenant, raw_key


@pytest_asyncio.fixture
async def api(tmp_path: Path) -> AsyncIterator[ApiFixture]:
    database_path = tmp_path / "spendledger-test.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{database_path}",
        auto_create_schema=True,
        log_level="WARNING",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        factory: SessionFactory = app.state.session_factory
        async with factory() as session:
            tenant, raw_key = await seed_tenant(
                session,
                settings=settings,
                name="Test Tenant",
            )
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield ApiFixture(
                client=client,
                api_key=raw_key,
                tenant_id=tenant.id,
                session_factory=factory,
            )
