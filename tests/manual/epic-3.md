# Epic 3 — a developer runs it

## Read this first

The walker is the owner, as a developer who has never seen this code. Use only the README.
If a step cannot be done from the README, that is a finding: write it down and move on.

## § 0 — Cold start

A new, empty folder. Python 3.11. Your own OpenRouter key. Nothing from this project's folder.

## § 1 — From the README to a conversation

**Preconditions as data:** a fresh clone; no `.env` in it yet.

| Step | Action | Expected |
|---|---|---|
| 1.1 | Follow README step 1: `git clone …` and `cd` | The folder has `app/`, `tests/`, `README.md`, `.env.example` — and no `memory/`, `demos/`, `spikes/` |
| 1.2 | Follow README steps 2–3: create `.env`, fill in the three values | — |
| 1.3 | Follow README step 4: `python3.11 -m app` | `ready · warm-up 200 · http://127.0.0.1:8765` |
| 1.4 | Follow README steps 5–6: open the page, type `ช่วยแนะนำหน่อยค่ะ` | Beanly answers; one row appears in the panel with intent, time and cost |
| 1.5 | Optional — README step 7: open `/?run=100` | 100 messages stream on the same screen; THROUGHPUT counts up (about $0.02) |
| 1.6 | README step 8: Ctrl-C | The app stops |

## Findings

| # | Step | What happened | Routed to |
|---|---|---|---|

## Sign-off

`Walked: [ ]  ·  by: ______  ·  date: ______  ·  Result: ______`
