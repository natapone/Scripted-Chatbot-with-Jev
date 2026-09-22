"""Session state — the contract `session-state.md` as code, and the only writer of `var/`.

`Session` holds every variable of the contract (§ The variables, § A snapshot): the session block,
the dialogue memory, the order form (declared here, written by Story 1.4) and the turn log. Two
fields are memory-only and never reach the snapshot: `raw` (each call's request and response
bodies, for the viewer) and `last_response` (what commit rule step 3 returns again for a repeated
`turn_id`). `transcript` is the bubbles the page shows — the reload restore and the masked history
sent to Jev are both built from it.

`Store` is the dict keyed by `session_id`, a lock per session, and the snapshot file
`<var_dir>/sessions/<session_id>.json` written atomically after every commit and loaded only when
the id is not in memory. A session expires `ttl_s` after its `updated_at`; an expired, unknown or
foreign-`flow_version` id is not found, and its snapshot is deleted. Nothing here calls Jev, reads
the flow file or knows the key.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.jev import now_utc, stamp

MEMORY_ONLY = ("raw", "last_response")   # in the process, never in the file


def flow_version_of(catalogue: Path) -> str:
    """sha256[:6] of the flow file's bytes — a session made under another file is ended."""
    return hashlib.sha256(catalogue.read_bytes()).hexdigest()[:6]


def empty_order() -> dict:
    """The order form, empty — contract § The order form. Story 1.4 writes it; this Story never does."""
    return {"lines": [], "promo_applied": None, "payment": None, "delivery_text": None,
            "recommend": {"brew": None, "roast": None}, "order_code": None, "confirmed_at": None}


@dataclass
class Session:
    # --- session
    session_id: str
    flow_version: str
    created_at: str
    updated_at: str
    turn_no: int = 0
    last_turn_id: str | None = None
    # --- dialogue memory
    contexts: dict = field(default_factory=dict)        # name → {expires_after_turn, params}
    focus_sku: str | None = None
    pending_prompt: dict | None = None                  # {slot, context, params}
    last_bot_message: dict | None = None                # {id, text, text_for_jev}
    live_buttons: list = field(default_factory=list)    # [{label, intent, params, message_id}]
    options_shown: list = field(default_factory=list)
    miss_count: int = 0
    promos_offered: list = field(default_factory=list)
    # --- the order form (Story 1.4 writes it)
    order: dict = field(default_factory=empty_order)
    # --- the turn log and the bubbles
    log: list = field(default_factory=list)
    transcript: list = field(default_factory=list)      # [{who: "you"|"bot", …}] as the page shows them
    # --- memory only
    raw: dict = field(default_factory=dict, repr=False)            # {"<turn_no>": {request, response}}
    last_response: dict | None = field(default=None, repr=False)   # commit rule 3

    @classmethod
    def new(cls, session_id: str | None = None, flow_version: str = "", now: datetime | None = None) -> "Session":
        at = stamp(now or now_utc())
        return cls(session_id=session_id or str(uuid.uuid4()), flow_version=flow_version,
                   created_at=at, updated_at=at)

    def copy(self) -> "Session":
        """The commit rule's copy: a deep copy of the state, the memory-only fields shared."""
        data = json.loads(json.dumps(self.to_snapshot(), ensure_ascii=False))
        s = Session.from_snapshot(data)
        s.raw, s.last_response = self.raw, self.last_response
        return s

    def to_snapshot(self) -> dict:
        d = dataclasses.asdict(self)
        for name in MEMORY_ONLY:
            d.pop(name, None)
        return d

    @classmethod
    def from_snapshot(cls, data: dict) -> "Session":
        names = {f.name for f in dataclasses.fields(cls)} - set(MEMORY_ONLY)
        return cls(**{k: v for k, v in data.items() if k in names})

    def live_contexts(self) -> list[str]:
        return list(self.contexts)


def parse_stamp(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


class Store:
    def __init__(self, flow_version: str, var_dir: Path, ttl_s: float = 1800, clock=now_utc):
        self.flow_version = flow_version
        self.dir = Path(var_dir) / "sessions"
        self.ttl_s = float(ttl_s)
        self.clock = clock
        self._sessions: dict[str, Session] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._master = threading.Lock()

    # --- lifecycle

    def new(self) -> Session:
        """A fresh session, in memory and not yet on disk — the first commit writes it."""
        s = Session.new(flow_version=self.flow_version, now=self.clock())
        with self._master:
            self._sessions[s.session_id] = s
        return s

    def get(self, session_id: str | None) -> Session | None:
        """Memory, else the snapshot; None when unknown, expired or made under another flow file."""
        if not session_id:
            return None
        with self._master:
            s = self._sessions.get(session_id)
        if s is None:
            s = self._load(session_id)
            if s is None:
                return None
            with self._master:
                s = self._sessions.setdefault(session_id, s)
        if s.flow_version != self.flow_version or self.expired(s):
            self.end(session_id)
            return None
        return s

    def expired(self, s: Session) -> bool:
        try:
            last = parse_stamp(s.updated_at)
        except ValueError:
            return True
        return (self.clock() - last).total_seconds() > self.ttl_s

    def lock(self, session_id: str) -> threading.Lock:
        with self._master:
            return self._locks.setdefault(session_id, threading.Lock())

    def commit(self, s: Session) -> None:
        """Swap the state in and write the snapshot: `updated_at` now, the file replaced atomically."""
        s.updated_at = stamp(self.clock())
        with self._master:
            self._sessions[s.session_id] = s
        self._write(s)

    def end(self, session_id: str) -> None:
        with self._master:
            self._sessions.pop(session_id, None)
            self._locks.pop(session_id, None)
        try:
            self.path(session_id).unlink()
        except FileNotFoundError:
            pass

    def in_memory(self, session_id: str) -> bool:
        with self._master:
            return session_id in self._sessions

    # --- the file

    def path(self, session_id: str) -> Path:
        if not session_id or "/" in session_id or "\\" in session_id or session_id in (".", ".."):
            raise ValueError("bad session id")
        return self.dir / f"{session_id}.json"

    def _write(self, s: Session) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.path(s.session_id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(s.to_snapshot(), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, target)

    def _load(self, session_id: str) -> Session | None:
        try:
            p = self.path(session_id)
        except ValueError:
            return None
        if not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return Session.from_snapshot(data) if isinstance(data, dict) else None
        except (ValueError, TypeError):
            return None
