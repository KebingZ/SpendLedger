from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        detail: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.metadata = metadata or {}


class AuthenticationError(ServiceError):
    def __init__(self, detail: str = "A valid API key is required.") -> None:
        super().__init__(status_code=401, code="authentication_failed", detail=detail)


class PermissionDeniedError(ServiceError):
    def __init__(self, scope: str) -> None:
        super().__init__(
            status_code=403,
            code="permission_denied",
            detail=f"The API key does not have the required '{scope}' scope.",
        )


class ConflictError(ServiceError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(status_code=409, code=code, detail=detail)


class NotFoundError(ServiceError):
    def __init__(self, resource: str) -> None:
        super().__init__(
            status_code=404,
            code="not_found",
            detail=f"{resource} was not found.",
        )


class InvalidTransitionError(ServiceError):
    def __init__(self, *, current: str, event: str) -> None:
        super().__init__(
            status_code=422,
            code="invalid_transaction_transition",
            detail=f"Event '{event}' cannot be applied while the transaction is '{current}'.",
        )


class ValidationServiceError(ServiceError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(status_code=422, code=code, detail=detail)
