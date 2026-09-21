---
type: schema
id: schema
status: active
owner: Natapone Charsombut
---

# Scripted-Chatbot-with-Jev — project schema

Structural only. No dates, no status narrative — those go in `memory/log.md`.

## Read first

1. `memory/product/profile.md` — project type, gates, tests, cold start, the do-not-read list
2. `memory/index.md` — the catalog; decide what to open from it
3. `memory/product/canon/user_brief.md` — what is being built, and the open doubts

## Memory layout

- `memory/source/` — what the owner gave us, in their own bytes. **The agent never edits anything
  here.** Provenance and digests are in `memory/source/index.md`. Owner rulings typed during work
  are appended to the day's `memory/source/YYYY-MM-DD_rulings.md`, verbatim.
- `memory/product/` — true until changed: canon, requirements, research, spikes, engineering.
- `memory/project/` — has a finish line: stories and results.
- `memory/log.md` — append-only, newest first. It links rulings; it never re-quotes them.

A restructured version of a source document is a new file in `memory/product/` that cites the
source — never an edit to the source.

## This is a public repo

- `.gitignore` is deny-by-default. A new top-level file or folder is unpublished until it is
  allowlisted there, on purpose.
- Secrets live only in `.env`, which is never committed. Never write a key, a token, or a raw API
  response containing one into any tracked file, log, spike result, or test fixture.
- Example data stays fictional. No real customer, contact, or bank details.

## Process

Built with the `npch` orb loops. Process files live in the plugin, not in this repo; friction with
the process is written up in `memory/product/improvements/`.
