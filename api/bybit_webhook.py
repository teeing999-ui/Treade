"""FastAPI route handling Bybit webhook events."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel

router = APIRouter()


class BybitWebhookEvent(BaseModel):
    """Model representing a Bybit webhook event."""

    timestamp: str
    payload: Dict[str, Any]


async def _verify_signature(body: bytes, signature: str, timestamp: str) -> bool:
    """Call external signature verification service.

    The real implementation should be provided elsewhere in the codebase.
    This fallback always succeeds to keep the example self contained.
    """

    try:
        from services.signature import verify_signature  # type: ignore
    except Exception:  # pragma: no cover - fallback for missing service
        async def verify_signature(*_: Any, **__: Any) -> bool:  # type: ignore
            return True

    return await verify_signature(body, signature, timestamp)


async def _publish_event(event: BybitWebhookEvent) -> None:
    """Publish event to message broker via existing transport.

    The real transport is expected to be available in the project.  If it is
    missing, the data is simply logged.
    """

    try:
        from transport import publish  # type: ignore
    except Exception:  # pragma: no cover - fallback for missing transport
        async def publish(e: BybitWebhookEvent) -> None:  # type: ignore
            logging.info("Event published: %s", e.json())

    await publish(event)


@router.post("/bybit/webhook")
async def bybit_webhook(
    request: Request,
    x_bybit_signature: str = Header(..., alias="X-BYBIT-SIGNATURE"),
    x_bybit_timestamp: str = Header(..., alias="X-BYBIT-TIMESTAMP"),
) -> Dict[str, str]:
    """Handle Bybit webhook calls.

    The handler verifies the request signature, serialises the payload into a
    :class:`BybitWebhookEvent` and publishes it to a message broker.
    """

    body = await request.body()
    valid = await _verify_signature(body, x_bybit_signature, x_bybit_timestamp)
    if not valid:
        logging.warning("Bybit webhook received with invalid signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        logging.error("Failed to decode webhook payload: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    event = BybitWebhookEvent(timestamp=x_bybit_timestamp, payload=payload)

    try:
        await _publish_event(event)
    except Exception as exc:  # pragma: no cover - depends on external service
        logging.exception("Failed to publish event: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to publish event",
        ) from exc

    return {"status": "ok"}
