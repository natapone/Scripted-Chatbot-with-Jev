"""`python3.11 -m app` — refuse plainly, or warm up, print the ready line, and serve."""
from __future__ import annotations

import sys

from app import config


def main(environ: dict | None = None, env_path=None) -> int:
    try:
        cfg = config.load(env_path=env_path, environ=environ)
    except config.ConfigError as e:
        print(f"refusing to start: {e}", file=sys.stderr)
        return 2

    from app import jev, server  # imported after the refusals: nothing else runs without a config

    status = jev.warm_up(cfg.key)
    httpd = server.make_server(cfg)
    print(f"ready · warm-up {status} · http://{cfg.host}:{cfg.port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
