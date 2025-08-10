import hmac
import hashlib
import config
from services.bybit_signature import verify_signature

def test_verify_signature_valid():
    config.BYBIT_WEBHOOK_SECRET = 'secret'
    payload = b'{"key":"value"}'
    recv_timestamp = '1587711043467'
    expected_signature = hmac.new(
        config.BYBIT_WEBHOOK_SECRET.encode(),
        recv_timestamp.encode() + payload,
        hashlib.sha256,
    ).hexdigest()
    assert verify_signature(payload, recv_timestamp, expected_signature)

def test_verify_signature_invalid():
    config.BYBIT_WEBHOOK_SECRET = 'secret'
    payload = b'{"key":"value"}'
    recv_timestamp = '1587711043467'
    invalid_signature = 'invalid'
    assert not verify_signature(payload, recv_timestamp, invalid_signature)
