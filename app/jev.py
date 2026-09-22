"""The one module that opens a connection to OpenRouter.

Story 1.1 gives it the warm-up call only (FR16 / spike S-1): the first call of a session is never
the customer's. The request is the spike's `noul` question — one yes/no over a Thai confirmation —
sent with `http.client` exactly as `run_spike.py` did. The key goes into the Authorization header
and nowhere else: not into the printed line, not into an exception, not into the return value.
"""
from __future__ import annotations

import http.client
import json

from app.config import MODEL

HOST, PATH = "openrouter.ai", "/api/v1/systemone"
TIMEOUT = 30

WARM_UP_BODY = {
    "model": MODEL,
    "state": {"shop_said": "สรุปออเดอร์: เฮาส์เบลนด์ 2 ถุง รวม 700 บาท ยืนยันออเดอร์ไหมคะ",
              "customer_said": "ยืนยันค่ะ"},
    "questions": {"confirm": {
        "type": "noul",
        "instructions": "The shop has just read the order back and asked the customer to confirm "
                        "it. Does the customer confirm the order?",
        "criteria": {"true": "ลูกค้าตกลง ยืนยัน หรือตอบรับ",
                     "false": "ลูกค้าปฏิเสธ ลังเล ขอเปลี่ยนแปลง หรือแก้ไขออเดอร์"}}},
}


def post(key: str, body: dict, connection=http.client.HTTPSConnection) -> tuple[int, dict]:
    """One POST /api/v1/systemone. Returns (status, parsed body); status 0 when no response came."""
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "X-Title": "jev-scripted-chatbot"}
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    conn = connection(HOST, timeout=TIMEOUT)
    try:
        conn.request("POST", PATH, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        return resp.status, data if isinstance(data, dict) else {}
    except OSError as e:  # DNS, refused, timeout — the message names the class, never the headers
        return 0, {"error": type(e).__name__}
    finally:
        conn.close()


def warm_up(key: str, connection=http.client.HTTPSConnection) -> int:
    """The throwaway first call. Prints `warm-up <status>` and returns the status (0 = no response)."""
    status, _ = post(key, WARM_UP_BODY, connection)
    print(f"warm-up {status}", flush=True)
    return status
