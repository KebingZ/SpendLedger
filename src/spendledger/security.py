from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spendledger.config import Settings
from spendledger.errors import AuthenticationError, PermissionDeniedError
from spendledger.models import ApiKey, Tenant


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    tenant_name: str
    api_key_id: str
    api_key_name: str
    scopes: frozenset[str]

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise PermissionDeniedError(scope)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key(settings: Settings) -> str:
    return f"{settings.api_key_prefix}{secrets.token_urlsafe(32)}"


async def create_api_key(
    session: AsyncSession,
    *,
    settings: Settings,
    tenant_id: str,
    name: str,
    scopes: list[str],
) -> tuple[ApiKey, str]:
    raw_key = generate_api_key(settings)
    key = ApiKey(
        tenant_id=tenant_id,
        name=name,
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[: min(12, len(raw_key))],
        scopes=sorted(set(scopes)),
    )
    session.add(key)
    await session.flush()
    return key, raw_key


async def authenticate_api_key(session: AsyncSession, raw_key: str) -> Principal:
    if not raw_key:
        raise AuthenticationError()
    result = await session.execute(
        select(ApiKey, Tenant)
        .join(Tenant, Tenant.id == ApiKey.tenant_id)
        .where(ApiKey.key_hash == hash_api_key(raw_key), ApiKey.enabled.is_(True))
    )
    row = result.one_or_none()
    if row is None:
        raise AuthenticationError()
    api_key, tenant = row
    return Principal(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        api_key_id=api_key.id,
        api_key_name=api_key.name,
        scopes=frozenset(api_key.scopes),
    )
