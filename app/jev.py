"""The one module that opens a connection to OpenRouter.

Story 1.1 gave it the warm-up call (FR16 / spike S-1): the first call of a session is never the
customer's. Story 1.2 adds `ask()` — one request built by `app/flow.py`, one typed `JevAnswer` back,
stamped to the millisecond with its cost. Requests go with `http.client` exactly as the spikes did.
The key goes into the Authorization header and nowhere else: not into the printed line, not into an
exception, not into the answer, not into its repr.

`host` and `timeout` default to OpenRouter's; `__main__.py` passes the Config's, so `JEV_HOST` can
point the client at a dead address for the agent's rehearsal only (Story 1.6). The owner's walk never
sets it.
"""
from __future__ import annotations

import http.client
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import MODEL

HOST, PATH = "openrouter.ai", "/api/v1/systemone"
TIMEOUT = 10

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


def now_utc() -> datetime:
    """The default clock. Tests pass their own."""
    return datetime.now(timezone.utc)


def stamp(t: datetime) -> str:
    """ISO-8601 UTC with milliseconds — `YYYY-MM-DDTHH:MM:SS.mmmZ` (owner ruling 2026-09-22)."""
    t = t.astimezone(timezone.utc) if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _to_ms(t: datetime) -> int:
    t = t.astimezone(timezone.utc) if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return int(t.timestamp()) * 1000 + t.microsecond // 1000


def connect(host: str, timeout: float, connection=http.client.HTTPSConnection):
    """`host` may carry a port (`127.0.0.1:1`); the class stays HTTPS — a dead port refuses first."""
    if ":" in host:
        name, port = host.rsplit(":", 1)
        return connection(name, int(port), timeout=timeout)
    return connection(host, timeout=timeout)


def post(key: str, body: dict, connection=http.client.HTTPSConnection, *,
         host: str = HOST, timeout: float = TIMEOUT) -> tuple[int, dict]:
    """One POST /api/v1/systemone. Returns (status, parsed body); status 0 when no response came."""
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "X-Title": "jev-scripted-chatbot"}
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    conn = connect(host, timeout, connection)
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


def warm_up(key: str, connection=http.client.HTTPSConnection, *,
            host: str = HOST, timeout: float = TIMEOUT) -> int:
    """The throwaway first call. Prints `warm-up <status>` and returns the status (0 = no response)."""
    status, _ = post(key, WARM_UP_BODY, connection, host=host, timeout=timeout)
    print(f"warm-up {status}", flush=True)
    return status


@dataclass(frozen=True)
class JevAnswer:
    """One call's answer, as the turn log's `jev` block records it. Never holds the key."""
    status: int                                   # HTTP status; 0 when no response came
    intent: str | None                            # `answers.intent.choice`
    confidence: float | None                      # `answers.intent.confidence`
    probabilities: dict[str, float] = field(default_factory=dict)
    entities: dict[str, str] = field(default_factory=dict)   # `answers.<entity>.choice`, the flow's entities
    cost_usd: float = 0.0                         # `usage.cost`
    request_id: str | None = None                 # `id`
    t_sent: str = ""                              # ISO-8601 UTC, milliseconds
    t_received: str = ""
    ms: int = 0                                   # t_received − t_sent, and nothing else
    error: str | None = None                      # None on a well-formed 200; "empty" on 200 without answers;
                                                  # the OSError class name on no response; "http" otherwise
    raw: dict = field(default_factory=dict, repr=False)   # the parsed response body, for the viewer


def ask(key: str, body: dict, *, connection=http.client.HTTPSConnection, clock=now_utc,
        host: str = HOST, timeout: float = TIMEOUT) -> JevAnswer:
    """Send one request built by `flow.build_request` and type the answer. Raises nothing for a
    failed or malformed call: `error` says why, `intent` is None, and the stamps are still set."""
    sent = clock()
    status, data = post(key, body, connection, host=host, timeout=timeout)
    received = clock()
    t_sent, t_received = stamp(sent), stamp(received)
    ms = _to_ms(received) - _to_ms(sent)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    cost = usage.get("cost") or 0.0
    request_id = data.get("id") if isinstance(data.get("id"), str) else None
    answers = data.get("answers") if isinstance(data.get("answers"), dict) else {}

    if status == 0:
        error = data.get("error") or "OSError"
    elif status != 200:
        error = "http"
    elif not answers:
        error = "empty"
    else:
        error = None

    intent_answer = answers.get("intent") if isinstance(answers.get("intent"), dict) else {}
    entities = {name: a["choice"] for name, a in answers.items()
                if name != "intent" and isinstance(a, dict) and isinstance(a.get("choice"), str)}
    probabilities = intent_answer.get("probabilities")
    return JevAnswer(status=status,
                     intent=intent_answer.get("choice") if error is None else None,
                     confidence=intent_answer.get("confidence") if error is None else None,
                     probabilities=dict(probabilities) if isinstance(probabilities, dict) else {},
                     entities=entities, cost_usd=float(cost), request_id=request_id,
                     t_sent=t_sent, t_received=t_received, ms=ms, error=error, raw=data)
