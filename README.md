# Scripted-Chatbot-with-Jev

A small demo of **Jev** (`typesafe/jev-1.13` on OpenRouter), a fast and cheap decision model.

- The demo is a Thai sales chatbot for a coffee shop, "Beanly".
- Every reply is written in advance. Jev does not write text.
- For each message the customer types, Jev chooses what it means (the intent) and picks out the
  details (product, quantity, payment, and so on). The bot then gives the prepared reply.
- A panel next to the chat shows every decision: the intent, the confidence, the time, and the cost.

## Results

Measured on 23 September 2026, from the recorded demo run.

| | Result |
|---|---|
| Messages | 1,000 customer messages, 32 at the same time |
| Total time | 23.7 seconds |
| **Throughput** | **42.3 messages per second** (one answer every 24 ms) |
| Correct | 99.2 % (992 of 1,000) |
| Total cost | ฿5.807 ($0.1751) |
| Cost per message | ฿0.0058 ($0.000175) |
| Tokens per message | 4,168 input, 586 output |
| One chat message alone | usually about 0.5 seconds |

How it was measured:

- The cost is the cost that OpenRouter reports for each call. Baht uses ฿33.17 per $1 (23 September 2026).
- Only input tokens are charged ($0.042 per million). Output tokens are free.
- Speed changes from day to day. Other runs of the same test took 26 to 35 seconds.

## Runbook: run it on your computer

You need:

- Python 3.11. Nothing else to install.
- Your own OpenRouter API key with a little credit (less than $1 is enough).

Steps:

1. Get the code.
   ```
   git clone https://github.com/natapone/Scripted-Chatbot-with-Jev.git
   cd Scripted-Chatbot-with-Jev
   ```
2. Create your settings file.
   ```
   cp .env.example .env
   ```
3. Open `.env` and fill in three values:
   - `OPENROUTER_API_KEY` — your OpenRouter key.
   - `THB_PER_USD` — the exchange rate used to show baht, for example `33.17`.
   - `RATE_DATE` — the date of that rate, for example `2026-09-23`.

   `.env` stays on your computer. Git never commits it.
4. Start the app.
   ```
   python3.11 -m app
   ```
   Wait for this line:
   ```
   ready · warm-up 200 · http://127.0.0.1:8765
   ```
5. Open http://127.0.0.1:8765 in your browser. You see Beanly's greeting and three buttons.
6. Chat. Click a button or type in Thai, for example `ช่วยแนะนำหน่อยค่ะ`. After each typed
   message, a new row appears in the panel on the right.
7. See the speed test. Open http://127.0.0.1:8765/?run=100 . The same chat screen shows 100
   customer messages answered very fast. The numbers at the bottom right count up.
8. Stop the app with Ctrl-C.

## What it costs you

| | About |
|---|---|
| One typed message | ฿0.006 ($0.0002) |
| One full order conversation | ฿0.04 |
| `/?run=100` | $0.02 |
| `/?run=1000` | $0.18 |

Clicking a button is free: a click does not call the model. For safety, the app stops calling the
model after $0.50 for each start (you can change this with `SPEND_CAP_USD` in `.env`).

## If something goes wrong

- **"refusing to start: OPENROUTER_API_KEY is missing"** or **"exchange rate is missing"** — check
  the three values in `.env`.
- **"cannot bind … Is another server on that port?"** — start on another port:
  `PORT=8770 python3.11 -m app`, then open http://127.0.0.1:8770 .
- **Rows say MODEL FAILED** — your key may be wrong or out of credit, or the network is down.
  Buttons still work.

## How it works

- `app/flow/catalogue.json` holds the conversation: every intent, the details to pick out,
  and the prepared replies. To change the bot, start with this file.
- `app/jev.py` sends one request to Jev for each typed message and reads back its choices.
- `app/turn.py` uses those choices and the conversation so far to pick the next prepared reply.

## Tests

No network and no key needed:

```
python3.11 -m unittest discover -s tests -t . -v
```

For maintainers: `.env.example` also lists switches for testing only (`JEV_HOST`, `JEV_TIMEOUT`,
`SESSION_TTL_S`, `VAR_DIR`). You do not need them to run the demo.

The example shop, products and customer details are made up.

## Licence

[MIT](LICENSE)
