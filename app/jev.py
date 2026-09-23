"""The one module that opens a connection to OpenRouter.

Story 1.1 gave it the warm-up call (FR16 / spike S-1): the first call of a session is never the
customer's. Story 1.2 adds `ask()` — one request built by `app/flow.py`, one typed `JevAnswer` back,
stamped to the millisecond with its cost. Requests go with `http.client` exactly as the spikes did.
The key goes into the Authorization header and nowhere else: not into the printed line, not into an
exception, not into the answer, not into its repr.

`host` and `timeout` default to OpenRouter's; `__main__.py` passes the Config's, so `JEV_HOST` can
point the client at a dead address for the agent's rehearsal only (Story 1.6). The owner's walk never
sets it.

Story 1.3 adds `Client`: one kept-alive HTTPS connection (finding F-3 — a fresh connection cost
939 ms against S-3's 332 on a kept-alive one), reconnected on any socket or protocol error, a lock
around the socket, and the process's own `spent_usd` / `calls` counters that the spend cap reads.
`ask(client=…)` and `warm_up(client=…)` go through it; without one they behave as in Story 1.2.

Story 2.1 adds `Client.sibling()` for the speed test's pool: another connection with the same key and
host, **no retry** (an error or a timeout is one failed call, counted — F-9), its own timeout, and the
same spend meter — so `spent_usd` and `calls` on the server's client count the pool too, and the
per-process spend cap sees every call.

Story 2.3 keeps two more things from each response: OpenRouter's own server time, from the
`Server-Timing` header's `cfWorker;dur=` (`JevAnswer.jev_ms` — its worker's time for the request,
upstream call to Jev included, client network excluded), and `usage.input_tokens` /
`usage.output_tokens`. `ms` stays the client's round trip; the cost stays `usage.cost`.
"""
from __future__ import annotations

import http.client
import json
import threading
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


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "X-Title": "jev-scripted-chatbot"}


def _exchange(conn, headers: dict, body: dict, meta: dict | None = None) -> tuple[int, dict]:
    """One request/response on an open connection. Raises what the socket raises. `meta`, when
    given, receives the response's `Server-Timing` header (None when absent)."""
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    conn.request("POST", PATH, body=payload, headers=headers)
    resp = conn.getresponse()
    if meta is not None:
        getheader = getattr(resp, "getheader", None)
        meta["server_timing"] = getheader("Server-Timing") if callable(getheader) else None
    raw = resp.read()
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    return resp.status, data if isinstance(data, dict) else {}


def server_ms(header: str | None) -> int | None:
    """OpenRouter's worker time from a `Server-Timing` header — the `cfWorker` entry's `dur`, in whole
    ms. None when the header, the entry or a number is missing."""
    if not isinstance(header, str):
        return None
    for metric in header.split(","):
        name, *params = [x.strip() for x in metric.split(";")]
        if name != "cfWorker":
            continue
        for param in params:
            key, _, value = param.partition("=")
            if key.strip() == "dur":
                try:
                    dur = float(value.strip().strip('"'))
                except ValueError:
                    return None
                return round(dur) if dur >= 0 and dur == dur and dur != float("inf") else None
    return None


def post(key: str, body: dict, connection=http.client.HTTPSConnection, *,
         host: str = HOST, timeout: float = TIMEOUT, meta: dict | None = None) -> tuple[int, dict]:
    """One POST /api/v1/systemone on a fresh connection. Returns (status, parsed body); status 0
    when no response came."""
    conn = connect(host, timeout, connection)
    try:
        return _exchange(conn, _headers(key), body, meta)
    except OSError as e:  # DNS, refused, timeout — the message names the class, never the headers
        return 0, {"error": type(e).__name__}
    finally:
        conn.close()


class Meter:
    """The spend and call counters one client and its siblings share; thread-safe."""

    def __init__(self):
        self._lock = threading.Lock()
        self.spent_usd = 0.0
        self.calls = 0

    def add(self, *, usd: float = 0.0, calls: int = 0) -> None:
        with self._lock:
            self.spent_usd += usd
            self.calls += calls


class Client:
    """One kept-alive connection to OpenRouter, shared by every turn of every session (F-3).

    `post(body)` sends on the open connection, opening one first when there is none. A socket or
    protocol error closes it; when the failed connection had already served a call (the server may
    have dropped an idle keep-alive), one retry goes out on a fresh connection before the call is
    reported as status 0. `spent_usd` sums `usage.cost` of every response; `calls` counts every
    attempt that reached a request, failed or not. The key lives in the headers dict only — the
    repr shows the host and the counters.
    """

    def __init__(self, key: str, host: str = HOST, timeout: float = TIMEOUT,
                 connection=http.client.HTTPSConnection, *, retry: bool = True, meter: "Meter | None" = None):
        self._headers = _headers(key)
        self.host, self.timeout, self._connection = host, timeout, connection
        self.retry = retry
        self._conn = None
        self._served = 0            # calls completed on the current connection
        self._lock = threading.Lock()
        self.meter = meter if meter is not None else Meter()

    @property
    def spent_usd(self) -> float:
        """`usage.cost` summed over every call on this client and its siblings."""
        return self.meter.spent_usd

    @property
    def calls(self) -> int:
        return self.meter.calls

    def sibling(self, timeout: float | None = None) -> "Client":
        """Another connection sharing this client's key, host and spend meter, with no retry."""
        c = Client.__new__(Client)
        c._headers = self._headers
        c.host, c._connection = self.host, self._connection
        c.timeout = self.timeout if timeout is None else timeout
        c.retry, c._conn, c._served, c._lock, c.meter = False, None, 0, threading.Lock(), self.meter
        return c

    def __repr__(self) -> str:
        return f"Client(host={self.host!r}, calls={self.calls}, spent_usd={self.spent_usd:.6f})"

    def _open(self):
        self._conn = connect(self.host, self.timeout, self._connection)
        self._served = 0
        return self._conn

    def _drop(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
        self._conn, self._served = None, 0

    def post(self, body: dict, meta: dict | None = None) -> tuple[int, dict]:
        with self._lock:
            self.meter.add(calls=1)
            attempts = 2 if self.retry and self._conn is not None and self._served > 0 else 1
            error = "OSError"
            for _ in range(attempts):
                conn = self._conn or self._open()
                try:
                    status, data = _exchange(conn, self._headers, body, meta)
                except (OSError, http.client.HTTPException) as e:
                    error = type(e).__name__
                    self._drop()
                    continue
                self._served += 1
                usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                self.meter.add(usd=float(usage.get("cost") or 0.0))
                return status, data
            return 0, {"error": error}

    def close(self) -> None:
        with self._lock:
            self._drop()


def warm_up(key: str, connection=http.client.HTTPSConnection, *,
            host: str = HOST, timeout: float = TIMEOUT, client: Client | None = None) -> int:
    """The throwaway first call. Prints `warm-up <status>` and returns the status (0 = no response).
    Through a `client` it opens that client's kept-alive connection, so the first customer turn
    reuses it."""
    if client is not None:
        status, _ = client.post(WARM_UP_BODY)
    else:
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
    ms: int = 0                                   # t_received − t_sent, and nothing else: the round trip
    error: str | None = None                      # None on a well-formed 200; "empty" on 200 without answers;
                                                  # the OSError class name on no response; "http" otherwise
    raw: dict = field(default_factory=dict, repr=False)   # the parsed response body, for the viewer
    jev_ms: int | None = None                     # Story 2.3: `Server-Timing` cfWorker dur — OpenRouter's server time
    input_tokens: int | None = None               # `usage.input_tokens`
    output_tokens: int | None = None              # `usage.output_tokens`


def ask(key: str | None, body: dict, *, connection=http.client.HTTPSConnection, clock=now_utc,
        host: str = HOST, timeout: float = TIMEOUT, client: Client | None = None) -> JevAnswer:
    """Send one request built by `flow.build_request` and type the answer. Raises nothing for a
    failed or malformed call: `error` says why, `intent` is None, and the stamps are still set.
    With a `client` the call goes over its kept-alive connection and `key` is not used."""
    sent = clock()
    meta: dict = {}
    if client is not None:
        status, data = client.post(body, meta)
    else:
        status, data = post(key or "", body, connection, host=host, timeout=timeout, meta=meta)
    received = clock()
    t_sent, t_received = stamp(sent), stamp(received)
    ms = _to_ms(received) - _to_ms(sent)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    cost = usage.get("cost") or 0.0
    tokens = {k: usage[k] if isinstance(usage.get(k), int) and not isinstance(usage.get(k), bool) else None
              for k in ("input_tokens", "output_tokens")}
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
                     t_sent=t_sent, t_received=t_received, ms=ms, error=error, raw=data,
                     jev_ms=server_ms(meta.get("server_timing")) if status else None, **tokens)
