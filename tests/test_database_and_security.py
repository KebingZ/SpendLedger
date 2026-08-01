from __future__ import annotations

import pytest
from sqlalchemy import select

from spendledger.database import session_scope
from spendledger.errors import AuthenticationError, PermissionDeniedError
from spendledger.models import Tenant
from spendledger.security import Principal, authenticate_api_key
from tests.conftest import ApiFixture


async def test_session_scope_commits_and_rolls_back(api: ApiFixture) -> None:
    async with session_scope(api.session_factory) as session:
        session.add(Tenant(name="Committed Tenant"))

    async with api.session_factory() as session:
        committed = await session.scalar(select(Tenant).where(Tenant.name == "Committed Tenant"))
        assert committed is not None

    with pytest.raises(RuntimeError, match="force rollback"):
        async with session_scope(api.session_factory) as session:
            session.add(Tenant(name="Rolled Back Tenant"))
            await session.flush()
            raise RuntimeError("force rollback")

    async with api.session_factory() as session:
        rolled_back = await session.scalar(
            select(Tenant).where(Tenant.name == "Rolled Back Tenant")
        )
        assert rolled_back is None


async def test_api_key_authentication_and_scope_checks(api: ApiFixture) -> None:
    async with api.session_factory() as session:
        principal = await authenticate_api_key(session, api.api_key)
        assert principal.tenant_id == api.tenant_id
        principal.require("spend:read")

        with pytest.raises(AuthenticationError):
            await authenticate_api_key(session, "")
        with pytest.raises(AuthenticationError):
            await authenticate_api_key(session, "sl_not-a-real-key")

    restricted = Principal(
        tenant_id=api.tenant_id,
        tenant_name="Test Tenant",
        api_key_id="key",
        api_key_name="restricted",
        scopes=frozenset({"spend:read"}),
    )
    with pytest.raises(PermissionDeniedError, match="spend:write"):
        restricted.require("spend:write")
