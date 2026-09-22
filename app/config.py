"""Configuration — the only place the OpenRouter key is read.

Sources, in order: the repo-root `.env`, then the process environment (which overrides it, so a
throwaway instance can say `PORT=8766` without editing the file). The key is never printed: the
Config's repr hides it, and every error message names the variable, not its value.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
HOST = "127.0.0.1"            # NFR2: reachable from this machine only — not configurable
MODEL = "typesafe/jev-1.13"
DEFAULT_PORT = 8765
JEV_HOST = "openrouter.ai"    # JEV_HOST / JEV_TIMEOUT: rehearsal only (Story 1.6, E-002) — the
JEV_TIMEOUT = 10.0            # owner's walk never sets them; absent, nothing differs


class ConfigError(Exception):
    """A plain, one-line reason the app refuses to start."""


@dataclass(frozen=True)
class Config:
    key: str = field(repr=False)
    thb_per_usd: float
    rate_date: str
    port: int = DEFAULT_PORT
    host: str = HOST
    model: str = MODEL
    jev_host: str = JEV_HOST          # `host[:port]` the client connects to, always over HTTPS
    jev_timeout: float = JEV_TIMEOUT  # seconds per call


def read_env_file(path: Path) -> dict[str, str]:
    """`NAME=value` lines; blanks and `#` comments skipped; quotes around a value stripped."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("'\"")
    return values


def load(env_path: Path | None = None, environ: dict | None = None) -> Config:
    """Build the Config or raise ConfigError with a plain reason. Prints nothing."""
    values = read_env_file(ENV_FILE if env_path is None else env_path)
    values.update(os.environ if environ is None else environ)

    key = values.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ConfigError("OPENROUTER_API_KEY is missing — put it in .env at the repo root "
                          "(see .env.example)")

    rate_raw = values.get("THB_PER_USD", "").strip()
    rate_date = values.get("RATE_DATE", "").strip()
    if not rate_raw or not rate_date:
        raise ConfigError("exchange rate is missing — set THB_PER_USD and RATE_DATE in .env; "
                          "baht on the panel needs a rate and the date it was taken")
    try:
        thb_per_usd = float(rate_raw)
    except ValueError:
        raise ConfigError(f"THB_PER_USD is not a number: {rate_raw!r}") from None
    if thb_per_usd <= 0:
        raise ConfigError(f"THB_PER_USD must be positive, got {rate_raw!r}")

    port_raw = values.get("PORT", "").strip() or str(DEFAULT_PORT)
    try:
        port = int(port_raw)
    except ValueError:
        raise ConfigError(f"PORT is not a number: {port_raw!r}") from None

    jev_host = values.get("JEV_HOST", "").strip() or JEV_HOST
    timeout_raw = values.get("JEV_TIMEOUT", "").strip() or str(JEV_TIMEOUT)
    try:
        jev_timeout = float(timeout_raw)
    except ValueError:
        raise ConfigError(f"JEV_TIMEOUT is not a number: {timeout_raw!r}") from None
    if jev_timeout <= 0:
        raise ConfigError(f"JEV_TIMEOUT must be positive, got {timeout_raw!r}")

    return Config(key=key, thb_per_usd=thb_per_usd, rate_date=rate_date, port=port,
                  jev_host=jev_host, jev_timeout=jev_timeout)
