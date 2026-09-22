"""Story 1.1 — hermetic suite: no network, no Jev, no `.env`. Every test passes a fake environment
and an empty env file, and the one HTTP call (the warm-up) is stubbed."""
from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path

from app import config
from app.__main__ import main

FAKE_KEY = "sk-or-v1-test-key-never-real"
GOOD = {"OPENROUTER_API_KEY": FAKE_KEY, "THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"}
NO_ENV_FILE = Path("/nonexistent/.env")


def load(environ):
    return config.load(env_path=NO_ENV_FILE, environ=environ)


class ConfigTests(unittest.TestCase):
    def test_refuses_without_key(self):
        with self.assertRaises(config.ConfigError) as cm:
            load({"THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"})
        self.assertIn("OPENROUTER_API_KEY is missing", str(cm.exception))
        # the entry point turns that into a non-zero exit and one plain line, starting no server
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(environ={"THB_PER_USD": "34.9", "RATE_DATE": "2026-09-22"}, env_path=NO_ENV_FILE)
        self.assertEqual(code, 2)
        self.assertEqual(err.getvalue().count("\n"), 1)
        self.assertIn("OPENROUTER_API_KEY is missing", err.getvalue())

    def test_refuses_without_rate(self):
        for partial in ({"OPENROUTER_API_KEY": FAKE_KEY},
                        {"OPENROUTER_API_KEY": FAKE_KEY, "THB_PER_USD": "34.9"},
                        {"OPENROUTER_API_KEY": FAKE_KEY, "RATE_DATE": "2026-09-22"}):
            with self.assertRaises(config.ConfigError) as cm:
                load(partial)
            self.assertIn("exchange rate is missing", str(cm.exception))
            self.assertNotIn(FAKE_KEY, str(cm.exception))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(environ={"OPENROUTER_API_KEY": FAKE_KEY}, env_path=NO_ENV_FILE)
        self.assertEqual(code, 2)
        self.assertIn("exchange rate is missing", err.getvalue())
        self.assertNotIn(FAKE_KEY, err.getvalue())

    def test_good_config(self):
        cfg = load(GOOD)
        self.assertEqual(cfg.key, FAKE_KEY)
        self.assertEqual(cfg.thb_per_usd, 34.9)
        self.assertEqual(cfg.rate_date, "2026-09-22")
        self.assertEqual((cfg.host, cfg.port, cfg.model), ("127.0.0.1", 8765, "typesafe/jev-1.13"))
        self.assertNotIn(FAKE_KEY, repr(cfg))  # the key is not in the Config's repr
        self.assertEqual(load({**GOOD, "PORT": "8766"}).port, 8766)
        # the .env file is read the same way, quotes stripped; the environment overrides it
        env = Path(__file__).parent / "_tmp.env"
        env.write_text('# comment\nOPENROUTER_API_KEY="from-file"\nTHB_PER_USD=35\nRATE_DATE=2026-01-01\n')
        try:
            self.assertEqual(config.load(env_path=env, environ={}).key, "from-file")
            self.assertEqual(config.load(env_path=env, environ={"THB_PER_USD": "36"}).thb_per_usd, 36.0)
        finally:
            env.unlink()


if __name__ == "__main__":
    unittest.main()
