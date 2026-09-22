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

    try:  # bind before the warm-up: a busy port should not cost a paid call
        httpd = server.make_server(cfg)
    except OSError as e:
        print(f"refusing to start: cannot bind http://{cfg.host}:{cfg.port} — {e.strerror or e}. "
              f"Is another server on that port? Try PORT=<n>.", file=sys.stderr)
        return 2
    status = jev.warm_up(cfg.key, host=cfg.jev_host, timeout=cfg.jev_timeout)
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
