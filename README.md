# Treade
Treading models

## Bybit Webhook Service

The service exposes a POST endpoint at `/bybit/events` for receiving webhooks from Bybit. The request body must be a JSON object representing the event data.

### Required headers

- `X-BYBIT-SIGNATURE` – HMAC SHA256 of the raw request body using `BYBIT_WEBHOOK_SECRET`.
- `X-BYBIT-TIMESTAMP` – Unix timestamp indicating when the webhook was sent.

### Response

On successful validation and parsing the service returns:

```json
{"status": "ok", "event": { ... }}
```

### Example request

```bash
curl -X POST https://example.com/bybit/events \
  -H 'Content-Type: application/json' \
  -H 'X-BYBIT-SIGNATURE: 0123456789abcdef' \
  -H 'X-BYBIT-TIMESTAMP: 1700000000000' \
  -d '{"type":"order.filled","data":{"order_id":"1","symbol":"BTCUSD","price":64000,"qty":1,"side":"Buy"}}'
```

### Configuring URL in Bybit

In the Bybit dashboard open **Broker → Webhook** (or API Management) and set the webhook URL to `https://<your-domain>/bybit/events`. Use the same secret configured via `BYBIT_WEBHOOK_SECRET` in the service settings.

