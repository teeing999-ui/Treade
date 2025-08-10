"""FastAPI route handling Bybit webhooks with signature verification and event publishing."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel

router = APIRouter()


class BybitWebhookEvent(BaseModel):
    """Serializable event for downstream processing."""
    timestamp: str
    payload: Dict[str, Any]


async def _publish_event(event: BybitWebhookEvent) -> None:
    """Publish event to message broker (fallback to logging if transport missing)."""
    try:
        from transport import publish  # type: ignore
    except Exception:  # pragma: no cover
        async def publish(e: BybitWebhookEvent) -> None:  # type: ignore
            logging.info("Event published (fallback log): %s", e.json())

    await publish(event)


async def _verify(body: bytes, timestamp: str, signature: str) -> bool:
    """Verify request signature using available project service.

    Supports either:
      - function: services.bybit_signature.verify_signature(body, timestamp, signature)
                  (or legacy 2-arg form: (body, signature))
      - class:    services.bybit_signature.BybitSignatureService(BybitSettings).verify(...)
    """
    # 1) Try functional API first
    try:
        from services.bybit_signature import verify_signature  # type: ignore
        try:
            ok = verify_signature(body, timestamp, signature)  # type: ignore[misc]
        except TypeError:
            ok = verify_signature(body, signature)  # type: ignore[misc]
        return bool(ok)
    except Exception:
        pass

    # 2) Fallback to OO service
    try:
        from config.bybit import BybitSettings  # type: ignore
        from services.bybit_signature import BybitSignatureService  # type: ignore
        svc = BybitSignatureService(BybitSettings())
        try:
            ok = svc.verify(body, signature, timestamp)  # type: ignore[misc]
        except TypeError:
            ok = svc.verify(body, signature)  # type: ignore[misc]
        return bool(ok)
    except Exception as exc:
        logging.exception("Signature verification unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Signature service unavailable",
        ) from exc


@router.post("/bybit/webhook")
async def bybit_webhook(
    request: Request,
    # Bybit may use either BYBIT-* (webhooks) or BAPI-* (unified) headers.
    x_bybit_signature: Optional[str] = Header(None, alias="X-BYBIT-SIGNATURE"),
    x_bybit_timestamp: Optional[str] = Header(None, alias="X-BYBIT-TIMESTAMP"),
    x_bapi_sign: Optional[str] = Header(None, alias="X-BAPI-SIGN"),
    x_bapi_timestamp: Optional[str] = Header(None, alias="X-BAPI-TIMESTAMP"),
) -> Dict[str, str]:
    """Handle Bybit webhook: verify signature → parse JSON → publish event."""

    body: bytes = await request.body()

    # Normalize headers (support both naming schemes)
    signature = x_bybit_signature or x_bapi_sign
    timestamp = x_bybit_timestamp or x_bapi_timestamp
    if not signature or not timestamp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing signature headers",
        )

    # Verify signature
    try:
        valid = await _verify(body, timestamp, signature)
    except HTTPException:
        raise
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

    # Parse JSON payload
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        logging.error("Failed to decode webhook payload: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    # Publish downstream event
    event = BybitWebhookEvent(timestamp=timestamp, payload=payload)
    try:
        await _publish_event(event)
    except Exception as exc:  # pragma: no cover
        logging.exception("Failed to publish event: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to publish event",
        ) from exc

    return {"status": "ok"}
