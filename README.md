# Scripted-Chatbot-with-Jev

A demo proof of concept: a scripted Thai sales chatbot whose conversation flow is traversed by
**Jev**, a fast, cheap decision model on OpenRouter — shown side by side with
[OpenThai-SystemOne](https://huggingface.co/iapp/OpenThai-SystemOne), an open-source Thai model
that mirrors Jev's request format and runs on a laptop. The chatbot answers from a predefined set of
replies; Jev's job at each node is to decide where the conversation goes next. The point of the
demo is to show Jev's speed and cost in a real-looking sales conversation.

## Status

**POC — two spikes are done; the chatbot is not built yet.** Spike S-1 checked how Jev behaves
through the OpenRouter API on Thai sales messages: 42 of 42 test messages routed correctly, about
345 ms per decision, about $0.00003 per decision. Those were clean, happy-path test messages, so
read it as "worth building", not as a measure of real-world accuracy. Spike S-2 ran
OpenThai-SystemOne on the identical messages: 36 of 42 on Thai, about 214 ms per decision on an
M4 Pro, no API cost — and nearly all of its misses were one behaviour, picking an explicit "none
of these" option too readily (55 of 57 on the same cases without it). Neither model was tuned.
Records, test cases and raw results are in `spikes/`. Next: design the conversation flow.

## Running it

There is no chatbot to run yet. You can re-run the spike (about $0.004 of OpenRouter credit):

```
cd spikes/S-1_jev_thai_node_routing
python3.11 -m venv .venv && source .venv/bin/activate   # standard library only
python run_spike.py --dry-run                           # builds every request, sends nothing
python run_spike.py --cap 0.50                          # stops itself at the cap
```
 You will need your own `OPENROUTER_API_KEY` in a local `.env` file — it is
ignored by git and must never be committed.

## Where things are

- `memory/product/profile.md` — what this project is: type, licence, how it is run and tested
- `memory/product/canon/user_brief.md` — what is being built and how success is judged
- `memory/source/` — the owner's original ask and the example material, unedited
- `memory/index.md` — catalog of every page · `memory/log.md` — what happened, newest first

The example sales material (the Beanly SOP and the product, FAQ and promotion tables) is
fictional demo data.

## Licence

[MIT](LICENSE)
