"""Verification of Bybit webhook signatures."""

from __future__ import annotations

import hmac
import hashlib
from typing import ByteString, Optional

import config
from config.bybit import BybitSettings


class BybitSignatureService:
    """Service for validating webhook signatures.

    Secret is injected via :class:`BybitSettings` for clean dependency management.
    """

    def __init__(self, settings: BybitSettings) -> None:
        self._secret = settings.webhook_secret.encode()

    def verify(self, body: ByteString, signature: str, timestamp: Optional[str] = None) -> bool:
        """Validate signature against the request body (and optional timestamp).

        Args:
            body: Raw request body from Bybit.
            signature: Value of the signature header.
            timestamp: Optional timestamp header. If provided, it is prepended to the body.

        Returns:
            True if the computed HMAC-SHA256 matches the provided signature.
        """
        message = (timestamp.encode() if timestamp else b"") + bytes(body)
        expected = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


def verify_signature(payload: bytes, recv_timestamp: str, signature: str) -> bool:
    """Legacy helper kept for backward compatibility with existing call sites.

    Uses `config.BYBIT_WEBHOOK_SECRET` and the same HMAC algorithm (timestamp + payload).
    """
    secret = config.BYBIT_WEBHOOK_SECRET.encode()
    message = recv_timestamp.encode() + payload
    expected_signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_signature, signature)
