"""Verification of Bybit webhook signatures."""

from __future__ import annotations

import hmac
import hashlib
from typing import ByteString

from config.bybit import BybitSettings


class BybitSignatureService:
    """Service for validating webhook signatures.

    The secret is injected via :class:`BybitSettings` allowing easy dependency
    injection in higher layers.
    """

    def __init__(self, settings: BybitSettings) -> None:
        self._secret = settings.webhook_secret.encode()

    def verify(self, body: ByteString, signature: str) -> bool:
        """Check that *signature* matches *body*.

        Args:
            body: Raw request body.
            signature: Signature header provided by Bybit.

        Returns:
            ``True`` if signature is valid, otherwise ``False``.
        """
        expected = hmac.new(self._secret, bytes(body), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
