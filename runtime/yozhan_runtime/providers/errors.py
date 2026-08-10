"""Shared provider error types, imported by both router.py and transports.py."""

from __future__ import annotations


class ProviderError(RuntimeError):
    pass


class ProviderHTTPStatusError(ProviderError):
    """Raised by a transport on a non-2xx HTTP response, so the router can
    inspect `.status_code` to decide whether to rotate keys (see keyring.py)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
