"""Bybit configuration settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol
import os


class ConfigService(Protocol):
    """Protocol for configuration providers."""

    def get(self, key: str) -> Optional[str]:
        """Return configuration value for *key* if present."""


@dataclass
class BybitSettings:
    """Settings for Bybit integrations.

    Attributes:
        webhook_secret: Secret used to validate incoming webhooks.
        broker_queue: Name of queue for broker events.
        allowed_ip_ranges: List of IP ranges allowed to access webhook.
    """

    webhook_secret: str
    broker_queue: str
    allowed_ip_ranges: List[str]


def load_bybit_settings(config_service: ConfigService | None = None) -> BybitSettings:
    """Load :class:`BybitSettings` from environment or a config service.

    Args:
        config_service: Optional external provider overriding environment variables.

    Returns:
        Constructed :class:`BybitSettings` instance.
    """

    def resolve(name: str) -> Optional[str]:
        if config_service is not None:
            value = config_service.get(name)
            if value is not None:
                return value
        return os.getenv(name)

    webhook_secret = resolve("BYBIT_WEBHOOK_SECRET") or ""
    broker_queue = resolve("BYBIT_BROKER_QUEUE") or ""
    ip_ranges = resolve("BYBIT_ALLOWED_IP_RANGES") or ""
    allowed_ip_ranges = [r.strip() for r in ip_ranges.split(",") if r.strip()]
    return BybitSettings(
        webhook_secret=webhook_secret,
        broker_queue=broker_queue,
        allowed_ip_ranges=allowed_ip_ranges,
    )
