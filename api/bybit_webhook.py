

from __future__ import annotations

import inspect
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


async def _publish_event(event: BybitWebhookEvent) -> None:
    """Publish event to message broker via existing transport.

    If a transport is unavailable, log the event instead.
    """
    try:
        from transport import publish  # type: ignore
    except Exception:  # pragma: no cover - fallback for missing transport
        async def publish(e: BybitWebhookEvent) -> None:  # type: ignore
            logging.info("Event published (fallback log): %s", e.json())

    await publish(event)


@router.post("/bybit/webhook")
async def bybit_webhook(
    request: Request,
    x_bybit_signature: str = Header(..., alias="X-BYBIT-SIGNATURE"),
    x_bybit_timestamp: str = Header(..., alias="X-BYBIT-TIMESTAMP"),
) -> Dict[str, str]:
    """Handle Bybit webhook calls.

    Steps:
      1) Read raw body.
      2) Validate signature via BybitSignatureService (uses BybitSettings).
         - If the service expects a `timestamp` argument, pass it; otherwise call with (body, signature).
      3) Parse JSON payload.
      4) Publish event to message broker.
    """

    # 1) Read raw body
    body: bytes = await request.body()

    # 2) Validate signature via project service
    try:
        from config.bybit import BybitSettings  # type: ignore
        from services.bybit_signature import BybitSignatureService  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on project wiring
        logging.exception("Signature service unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signature service unavailable",
        ) from exc

    validator = BybitSignatureService(BybitSettings())
    try:
        # Prefer 3-arg call if supported (body, signature, timestamp)
        verify_sig = validator.verify  # type: ignore[attr-defined]
        if "timestamp" in inspect.signature(verify_sig).parameters:
            valid = verify_sig(body, x_bybit_signature, x_bybit_timestamp)  # type: ignore[misc]
        else:
            valid = verify_sig(body, x_bybit_signature)  # type: ignore[misc]
    except TypeError:
        # Fallback to legacy 2-arg signature
        valid = validator.verify(body, x_bybit_signature)  # type: ignore[misc]
    except Exception as exc:
        logging.exception("Error during signature verification: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signature verification failed",
        ) from exc

    if not valid:
        logging.warning("Bybit webhook received with invalid signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )

    # 3) Parse JSON payload
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        logging.error("Failed to decode webhook payload: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    # 4) Publish event
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
