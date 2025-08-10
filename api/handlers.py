from __future__ import annotations

from dataclasses import asdict
from fastapi import FastAPI, HTTPException

from models.bybit_events import BybitEvent, parse_event

app = FastAPI()


@app.post("/bybit/events")
async def handle_bybit_event(payload: dict) -> dict:
    """Webhook endpoint to process Bybit events."""
    try:
        event: BybitEvent = parse_event(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "event": asdict(event)}
