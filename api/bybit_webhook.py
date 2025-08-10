from fastapi import APIRouter, Request, HTTPException
from services.bybit_signature import verify_signature

router = APIRouter()

@router.post('/bybit')
async def bybit_webhook(request: Request):
    payload = await request.body()
    recv_timestamp = request.headers.get('X-BAPI-TIMESTAMP', '')
    signature = request.headers.get('X-BAPI-SIGN', '')
    if not verify_signature(payload, recv_timestamp, signature):
        raise HTTPException(status_code=401, detail='Invalid signature')
    return {'status': 'ok'}
