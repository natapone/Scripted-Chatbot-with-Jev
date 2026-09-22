"""Scripted Chatbot with Jev — the local demo server. Python 3.11 standard library only.

`python3.11 -m app` reads `.env`, makes one warm-up call to Jev, prints the ready line and serves
the approved screen on 127.0.0.1. The OpenRouter key lives in `app.config`'s process memory and
leaves it only through `app.jev`, the one module that opens a connection to OpenRouter.
"""
