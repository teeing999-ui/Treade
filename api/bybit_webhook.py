"""API layer for Bybit webhooks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ByteString

from config.bybit import BybitSettings
from services.bybit_signature import BybitSignatureService


@dataclass
class BybitWebhookAPI:
    """Handle incoming Bybit webhooks.

    Settings are injected to keep the endpoint easily testable and configurable.
    """

    settings: BybitSettings

    def handle(self, body: ByteString, signature: str) -> bool:
        """Process a webhook request.

        Args:
            body: Raw request body received from Bybit.
            signature: Signature header from request.

        Returns:
            ``True`` if signature is valid.
        """
        validator = BybitSignatureService(self.settings)
        return validator.verify(body, signature)
