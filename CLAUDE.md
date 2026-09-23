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

### Commit rules

- **Published, and nothing else:** `app/`, `tests/`, `README.md`, `LICENSE`, `CLAUDE.md`,
  `.env.example`, `.gitignore`.
- **Local only:** `memory/`, `prototypes/`, `spikes/`, `var/`. The loops read and write them on disk;
  they are never staged, never committed, never `git add -f`. Where a process step says "commit the
  Story / the views / the log", it means save the file.
- **Before every commit:** `git diff --cached --name-only` — any path outside the published list
  stops the commit.
- **Commit messages** say what changed in the code. They never quote private records, the owner's
  rulings, a key, or customer data.
- **Nothing is pushed** without the owner saying so. Before a push, `git log --all --name-only` must
  show no local-only path.

## Process

Built with the `npch` orb loops. Process files live in the plugin, not in this repo; friction with
the process is written up in `memory/product/improvements/`.
