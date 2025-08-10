import hmac
import hashlib
import config

def verify_signature(payload: bytes, recv_timestamp: str, signature: str) -> bool:
    message = recv_timestamp.encode() + payload
    expected_signature = hmac.new(
        config.BYBIT_WEBHOOK_SECRET.encode(), message, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)
