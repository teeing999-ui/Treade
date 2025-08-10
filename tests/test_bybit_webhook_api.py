import hashlib
import hmac
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient

from api.bybit_webhook import BybitWebhookAPI
from config.bybit import BybitSettings


# Helper to build a minimal FastAPI app around BybitWebhookAPI

def create_app(api: BybitWebhookAPI, broker: Mock) -> FastAPI:
    app = FastAPI()

    @app.post("/webhook")
    async def webhook(request: Request, x_bybit_signature: str = Header(...)) -> dict:
        body = await request.body()
        if not api.handle(body, x_bybit_signature):
            raise HTTPException(status_code=403, detail="invalid signature")
        try:
            broker.publish(api.settings.broker_queue, body)
        except Exception as exc:  # pragma: no cover - tested via mocks
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"status": "ok"}

    return app


@pytest.fixture()
def api_settings() -> BybitSettings:
    return BybitSettings(webhook_secret="top-secret", broker_queue="bybit-events", allowed_ip_ranges=[])


@pytest.fixture()
def api(api_settings: BybitSettings) -> BybitWebhookAPI:
    return BybitWebhookAPI(settings=api_settings)


@pytest.fixture()
def broker() -> Mock:
    return Mock()


@pytest.fixture()
def client(api: BybitWebhookAPI, broker: Mock) -> TestClient:
    app = create_app(api, broker)
    return TestClient(app)


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_success(client: TestClient, api_settings: BybitSettings, broker: Mock) -> None:
    body = b"{}"
    signature = _sign(body, api_settings.webhook_secret)

    response = client.post("/webhook", data=body, headers={"X-Bybit-Signature": signature})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    broker.publish.assert_called_once_with(api_settings.broker_queue, body)


def test_webhook_invalid_signature(client: TestClient, broker: Mock) -> None:
    body = b"{}"
    response = client.post("/webhook", data=body, headers={"X-Bybit-Signature": "invalid"})

    assert response.status_code == 403
    broker.publish.assert_not_called()


def test_webhook_broker_exception(client: TestClient, api_settings: BybitSettings, broker: Mock) -> None:
    body = b"{}"
    signature = _sign(body, api_settings.webhook_secret)
    broker.publish.side_effect = RuntimeError("broker failure")

    response = client.post("/webhook", data=body, headers={"X-Bybit-Signature": signature})

    assert response.status_code == 502
    broker.publish.assert_called_once_with(api_settings.broker_queue, body)
