from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Type, TypeVar

T = TypeVar('T', bound='BybitEvent')


@dataclass
class BybitEvent:
    """Base class for all Bybit events."""

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """Parse event data from a raw dict."""
        return cls(**data)


@dataclass
class OrderFilledEvent(BybitEvent):
    order_id: str
    symbol: str
    price: float
    qty: float
    side: str


@dataclass
class OrderCanceledEvent(BybitEvent):
    order_id: str
    reason: str


EVENT_TYPE_MAP = {
    "order.filled": OrderFilledEvent,
    "order.canceled": OrderCanceledEvent,
}


def parse_event(data: Dict[str, Any]) -> BybitEvent:
    """Convert raw dictionary into a concrete event model."""
    event_type = data.get("type")
    model = EVENT_TYPE_MAP.get(event_type)
    if not model:
        raise ValueError(f"Unsupported event type: {event_type}")
    payload = data.get("data", data)
    return model.from_dict(payload)
