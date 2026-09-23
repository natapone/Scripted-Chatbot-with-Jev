# Scripted-Chatbot-with-Jev

A demo proof of concept: a scripted Thai sales chatbot whose conversation flow is traversed by
**Jev**, a fast, cheap decision model on OpenRouter. The chatbot answers from a predefined set of
replies; Jev's job at each node is to decide where the conversation goes next. The point of the
demo is to show Jev's speed and cost in a real-looking sales conversation.

## Status

**POC — the chat is built: an intent-based bot, every typed sentence routed by Jev, with a panel showing each decision's time and cost.** Before it was built, spike S-1 checked how Jev behaves
through the OpenRouter API on Thai sales messages: 42 of 42 test messages routed correctly, about
345 ms per decision, about $0.00003 per decision. Those were clean, happy-path test messages, so
read it as "worth building", not as a measure of real-world accuracy. Spike S-3 then put a
whole predefined intent catalogue — about 24 intents, Dialogflow-style — into one question, with
five entity questions in the same call: 121 of 125 Thai messages matched the right intent, every
named value was found, at about 330 ms and $0.00016 a turn when the API was healthy. (It was not
always: one run hit 57 empty responses in a row.) The spikes' records and the design documents are
kept out of this repo; the conversation itself — every intent, entity, context and reply — is
`app/flow/catalogue.json`.

## Running it

Python 3.11, standard library only — nothing to install.

```
cp .env.example .env        # then fill in the three names: your OpenRouter key, the THB/USD
                            # rate and the date it was taken. .env is ignored by git.
python3.11 -m app           # one warm-up call to Jev, then: ready · warm-up 200 · http://127.0.0.1:8765
```

Open `http://127.0.0.1:8765/`. The server binds to 127.0.0.1 only; the key stays in the server
process and never reaches the browser. It refuses to start, with one plain line, when the key or
the rate is missing. `PORT=8766 python3.11 -m app` starts a second, throwaway instance.
`JEV_HOST=127.0.0.1:1 python3.11 -m app` rehearses "Jev unreachable" (`ready · warm-up 0 · …`) — for the agent's rehearsal only, never the owner's walk.

Tests (no network, no Jev): `python3.11 -m unittest discover -s tests -t . -v`

The conversation is reachable without the page: `GET /api/session?id=` starts or restores a session, `POST /api/turn` sends one typed or clicked message (the shapes are in `app/server.py`); snapshots live in `var/sessions/`, never committed.

## Where things are

- `app/` — the server (`server.py`), the turn loop (`turn.py`), the order form (`order.py`), the Jev
  client (`jev.py`), the flow file (`flow/catalogue.json`) and the page (`static/`)
- `tests/` — the suite (hermetic: no network, no Jev); `tests/manual/` — the walk runbooks a person
  follows; `tests/rehearsal/` — the agent's measurement scripts against real Jev

The example sales material (the Beanly SOP and the product, FAQ and promotion tables) is
fictional demo data.

## Licence

[MIT](LICENSE)
