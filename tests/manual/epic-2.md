---
type: walk
id: walk-epic-2
status: draft — written with the Epic, before any of its code
owner: Natapone Charsombut
updated: 2026-09-23
---

# Epic 2 — Presenter walks PR-1

## Read this first

The walker is the **owner**, as the presenter. The walk has two halves: the **speed test** on the
chat screen (§ 1), which this Epic builds — the same screen with nothing added, started from the
address and run very fast — and **stop 3** of the demo video, the truth check (§ 4).
Stops 1 and 2 — the audience and one sentence, the storyboard — were confirmed before the build and
are recorded in §§ 2–3, not walked. The walk ends at the truth check: the video stays a local file
the owner takes; publishing the code, and the README for people who clone it, belong to Epic 3.
Written before the build, from the flow PR-1, the confirmed storyboard and the
prototype walk records, whose control labels and landings were proven in a browser against the
prototype.

> **Every action goes through a real surface.** No direct API call, no database client, no seed
> script. **If something cannot be done from a surface, that is a FINDING** — write it down and
> move on.

> A terminal used to **measure** is allowed, and is named in the step table. A terminal used to
> **achieve** a product outcome is a **FINDING**.

The cold start in § 0 is the operator's job, not the product's, and is exempt. So is the second,
lowered-cap instance in § 1.9: starting a server with a setting is operating it, and what is walked
is the refusal on the page. Opening an address with `?run=100` is the surface the speed test is
started from; it is walked, not an exception.

## § 0 — Cold start and hazards

**Readiness:** *Epic 1 of 3 built · 1 signed* — this is Epic 2 of 3 in the build order, after the
signed customer chat. It is walked against the dry-walk record of Story 2.4 (local, not published);
any red row there is read out before step 1.1.

> 📍 **Where you are now** — the walk is longer than one sitting, because the agent rehearses and
> records between § 1 and § 4. Your steps, in order: **§ 1** the speed test at 100 and the cap
> refusal (about ten minutes) → *(the agent rehearses and records — you are not needed)* → **§ 4**
> watch the WebM, rule on each claim, sign. Stops 1 and 2 are already done (§§ 2–3). Each section
> starts from the state its preconditions name, so a pause costs one section, not the walk.

The cold start is the project's, verbatim, on **port 8768**: on this machine 8765 and 8766 are held
by other processes.

* **Agent runs**: deletes `/Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/var/sessions/*`
  (session snapshots — nothing else lives there; it names the file count before deleting). Confirms
  `.env` holds `OPENROUTER_API_KEY`, `THB_PER_USD` and `RATE_DATE` **without printing the key**, and
  reads out the rate and its date — they are the ones for recording day. Reads out the spend used so
  far against the $1.00 cap. Runs 0.a–0.c.
* **You run, in your own terminal** (foreground — do not background it):

  ```
  cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev
  cp .env.example .env     # once: OPENROUTER_API_KEY, THB_PER_USD, RATE_DATE — .env is ignored by git
  PORT=8768 python3.11 -m app        # one warm-up call to Jev, then the ready line
  ```

* **Ready when**: the terminal prints `ready · warm-up 200 · http://127.0.0.1:8768`. It refuses,
  with one line on stderr and exit code 2, when the key or the rate is missing. Stop it with Ctrl-C.

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 0.a | 🤖 💻 Measure: the repo publishes nothing it should not | `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && git status --short --ignored \| grep -E '^\?\?' ; git check-ignore -v .env var/sessions/probe` | No `??` line; `.env` and `var/` reported ignored |
| 0.b | 🤖 💻 Measure: the key is in no served or committed file | `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && python3 -c "import re,subprocess;k=re.search(r'OPENROUTER_API_KEY=(\S+)',open('.env').read()).group(1);print(subprocess.run(['grep','-rl','--exclude-dir=.git','--exclude=.env','--exclude-dir=var',k,'.'],capture_output=True,text=True).stdout or 'clean')"` | `clean` |
| 0.c | 🤖 💻 Measure: the two ports this walk uses are free before the start | `lsof -nP -iTCP:8768 -iTCP:8769 -sTCP:LISTEN` | No output (then the owner starts the server; after it, 8768 only) |

| Hazard | What goes wrong |
|---|---|
| Every speed-test message is a paid call to Jev | **100 ≈ $0.016; 1,000 ≈ $0.163.** The walker only ever opens **`/?run=100`**. The 1,000 run happens once, in the agent's recording, and only with $0.17 of room left under the $1.00 cap |
| Jev's API can time out or return empty answers under load | In the speed test they are **counted as errors** in the run's figures (read at 1.5), never retried silently; a handful is the designed behaviour, not a finding. A run with more than 1 % errors is a finding |
| The recorded cut is only true for the build it recorded | Any change to `app/` after the recording means re-recording the whole pass; § 4's preconditions check it |

## § 1 — The speed test on the chat screen

The speed test adds **nothing** to the page: no control, no chooser, no button, no status or summary
line. It is the same chat screen, started from the address — `/?run=100` here, `/?run=1000` only in
the agent's recording — and it simply streams very fast. The totals are the key-info block's.

**Preconditions as data:** the server on `http://127.0.0.1:8768` has printed its ready line; the
browser shows a fresh session — the greeting is the only bubble, the key-info block reads
`— · ฿0.000 · 0`, no panel rows. At least $0.02 of room under the cap. Nothing listens on 8769.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 1.1 | 👤 🌐 Open the page with no parameter | `http://127.0.0.1:8768/` | The greeting and its buttons; key-info at zero; the panel header reads `jev-1.13` **legibly**, `● live`, and the rate with its date. `เริ่มใหม่` at the top right responds to a click. **No speed-test control anywhere** — no `speed test ▾`, no *not wired* text — and nothing streams |
| 1.2 | 👤 🌐 Open the address that starts the run, and watch — click nothing | `http://127.0.0.1:8768/?run=100` | The greeting for a moment, then customer bubbles and Beanly's prepared replies stream **very fast in the chat column**; panel rows stream beside them as usual; the key-info block's TURNS and TOTAL COST count up. Nothing is added to the page. The address bar drops `?run=100` once the run starts. A delivery-details message shows as `[delivery details]`. The whole panel (rows and key-info) is in view |
| 1.3 | 👤 🌐 Wait for the end | the page | The stream stops within a few seconds, not a minute — the messages were in flight together. The last chats and the key-info totals stay: TURNS reads 100; AVG RESPONSE and TOTAL COST (about ฿0.5 at a rate near 34) are filled. At most 40 bubbles and 50 rows on screen |
| 1.4 | 🤖 💻 Measure: the figures come from the log | `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && python3 -c "import json,glob,os;f=max(glob.glob('var/sessions/*.json'),key=os.path.getmtime);L=json.load(open(f))['log'];u=sum((e.get('jev') or {}).get('cost_usd') or 0 for e in L);print('entries',len(L),'\| usd',round(u,6),'\| not matched',sum(e['outcome']!='matched' for e in L),'\| masked',sum((e.get('input') or {}).get('text')=='[delivery details]' for e in L))"` | `entries 100`; `usd` about 0.016, and `usd × the rate` equals TOTAL COST to the digits shown; `not matched` is a handful; `masked` equals the delivery-details messages in the run (above 0) — no delivery phrase is in the log unmasked |
| 1.5 | 🤖 💻 Measure: the recap figures the server computed — the ones the driver reads | `curl -s` on the run route Story 2.1 names (recorded in the dry-walk file), read out | Calls 100; total time and calls per second consistent with 1.3; average ms equals AVG RESPONSE; share correct, and errors counted (a handful at most); total $ equals 1.4's `usd`, total ฿ equals TOTAL COST; cost per call = total ÷ 100. None of these is drawn on the page beyond the key-info block |
| 1.6 | 👤 🌐 Click **open** on the newest panel row | the page | The viewer shows a full-catalogue request — every intent in scope and the five entity questions — and the response with its cost in US dollars; the key-info block is not covered. Close it |
| 1.7 | 👤 🌐 Click **เริ่มใหม่** | chat header | The greeting alone; key-info back to zero; no rows; **no second run starts** |
| 1.8 | 👤 🌐 Type **ค่าส่งเท่าไหร่คะ**, Enter | composer | The prepared shipping answer and one panel row — the chat works as before the run |
| 1.9 | 👤 💻 Start a second, lowered-cap instance in another terminal | `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && PORT=8769 SPEND_CAP_USD=0.001 python3.11 -m app` | `ready · warm-up 200 · http://127.0.0.1:8769` |
| 1.10 | 👤 🌐 Open the lowered-cap instance at the run address | `http://127.0.0.1:8769/?run=100` | The run is refused before its first call: the key-info status line reads **`● spend cap reached`**; **nothing streams**, no row appears, TURNS stays 0, no dialog box, nothing else on the page changes. Then Ctrl-C the 8769 terminal |

Notes: 1.4 and 1.5 are run right after 1.3, before 1.7 starts a new session file. The correct count
is scored against the test set's labels; a handful short of 100 is the model's real accuracy on
video, not a defect.

### § 1 Deltas — the page since this runbook was written

The rows above were written before the key-info block gained its fourth figure and AVG RESPONSE
changed to the provider's server time. Where a row and this list disagree, this list is the build:

| Row | Read it as |
|---|---|
| Preconditions | The key-info block has **four** figures and reads `— · ฿0.000 · 0 · —` (AVG RESPONSE · TOTAL COST · TOTAL TURNS · AVG TOKENS / TURN) |
| 1.3 | AVG RESPONSE is OpenRouter's **server time** (`Server-Timing` cfWorker), not the round trip; AVG TOKENS / TURN is filled too (about 4,200). At a rate near 33, TOTAL COST is about **฿0.6** |
| 1.5 | The route is `curl -s 'http://127.0.0.1:8768/api/run?session_id=<id>&since=100'`, where `<id>` is the name of the file 1.4 read (without `.json`); the figures are under `recap`. **`avg_jev_ms` equals AVG RESPONSE**; `avg_ms` is the average round trip and is larger. `avg_input_tokens` equals AVG TOKENS / TURN |
| 1.10 | Besides the status line, the header's badge reads **CAP** instead of LIVE — the cap's own state. Nothing else changes |

## §§ 2–3 — Stops 1 and 2: a record, not walked

Both confirmed by the owner on 2026-09-23, **before any of Epic 2 was built**:

* **Stop 1** — who watches, the five ideas, the one sentence, Thai chat with English overlay:
  confirmed.
* **Stop 2** — the storyboard, five chapters in two sessions (session 1 = chapters 1–3, the chat;
  session 2 = chapters 4–5, the speed test at 1,000 and its recap card, then the end card):
  confirmed, at `/Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/demos/developers-2026-09-23/storyboard.md`
  (local only).
* **`demo_lint`**: green on that storyboard.

A change to the storyboard after this point is a return to stop 2, and everything after it is redone.

**Between § 1 and § 4 — the agent's, not walked.** The rehearsal: overlays off, from a cold start,
every planned typed sentence checked for the exit the storyboard expects, the speed test at **100,
never 1,000**; any product defect fixed, not worked around. **A planned sentence Jev misroutes comes back to you**: show it honestly, or choose another sentence — it is never hidden. Then the recording at **1920×1080, 100 %, `devicePixelRatio` 1, no zoom** — each session one
continuous pass, no resume, no splice — the page opened at `/?run=1000`; chapter 5's recap figures computed
by the server and read by the driver, never typed, and drawn as a video overlay. The MOV is made from the WebM with `ffmpeg`. The rehearsal is reported as rows with a verdict
each before § 4 starts; a red row means no recording. If Jev becomes unreachable during the
recording, the pass is abandoned and recorded again whole; if the spend cap is reached, recording
stops and you are asked.

## § 4 — Stop 3: the truth check

**Preconditions as data:** the video's folder in `demos/` holds the WebM, the MOV made from it,
`chapters.json`, `youtube.md` (Thai) and the ledger — no `deck.html`, no narration script; the ledger names the provider (OpenRouter), the
model (`typesafe/jev-1.13`), the rate with its source and date, the pass's cost, and chapter 5's
recap figures as the driver read them; the rehearsal report has no red row; no commit has touched
`app/` since the recording started.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 4.1 | 🤖 💻 Measure: the deliverables exist | `ls -l /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/demos/developers-2026-09-23/ && ffprobe -v error -show_entries stream=width,height -show_entries format=duration /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/demos/developers-2026-09-23/*.webm /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/demos/developers-2026-09-23/*.mov` | The WebM, the MOV, `chapters.json`, `youtube.md` and the ledger, each with a byte size; no `deck.html` and no narration script; for both the WebM and the MOV `width=1920`, `height=1080`, and a duration that matches `chapters.json`'s last chapter end |
| 4.2 | 👤 🎬 Watch the whole WebM, start to finish | the WebM | Session 1 (chapters 1–3) then session 2 (chapters 4–5), each one continuous pass, no jump; it ends on the recap card, then the end card. The key-info block is in shot throughout; no chapter card, callout or subtitle covers the chat or a figure |
| 4.3 | 👤 🎬 For each chapter, answer *is this true today?* | the chapter list with its drive column, beside the video | Every claim **yes**, and every English subtitle says what the Thai screen says. A **no** becomes a re-worded subtitle, a label, or a cut chapter — and any change to the recording means re-recording the whole pass |
| 4.4 | 👤 🎬 Check chapter 5's recap against the ledger | the recap card in the video; the ledger | Each figure — calls, total time, calls per second, average ms, share correct, total ฿ and $, cost per call — equals the ledger's, and agrees with the key-info totals on screen behind it (turns, total ฿, average ms) |
| 4.5 | 👤 🎬 Check the frame | the video | The panel header's `jev-1.13` is legible; the rate and date on screen match the ledger's; **no zoom** — the page is at the same scale in every chapter, and the ledger records zoom 1.0 and `devicePixelRatio` 1 for each |
| 4.6 | 👤 📄 Read `youtube.md` | `/Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/demos/developers-2026-09-23/youtube.md` | In Thai: a title, a description, the chapter timestamps — equal to `chapters.json`'s starts — and tags. It claims nothing the video does not show |
| 4.7 | 🤖 💻 Measure: the spend, and the key in no log or recorded result | the ledger and the project's spend line, read out; then `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && python3 -c "import re,subprocess;k=re.search(r'OPENROUTER_API_KEY=(\S+)',open('.env').read()).group(1);print(subprocess.run(['grep','-rl','--exclude-dir=.git','--exclude=.env',k,'.'],capture_output=True,text=True).stdout or 'clean')"` | The pass's cost is in the ledger; the POC's total stays under $1.00; `clean` — now including `var/` and the video's folder |

## Findings

| # | What happened | Where | Severity | → destination |
|---|---|---|---|---|
| | | | | |

Severity: blocked the walk / wrong on screen / cosmetic. Every finding gets a destination before
sign-off. A blocking finding in § 1 may be fixed and § 1 re-walked from its preconditions. A finding
at § 4 that changes the product or a claim goes back to stop 2 (the storyboard, §§ 2–3) and everything after it
is redone — the recording is never patched.

## Sign-off

| AC | What the walker ruled | ✓ |
|---|---|---|
| AC-1 | Opened at `/?run=100`, the speed test streams as chat on the same screen; nothing added to the page | [ ] |
| AC-2 | Its figures come from the log: count, cost, correct, errors | [ ] |
| AC-3 | The key-info totals stand; start-over clears and starts no second run; the chat works after | [ ] |
| AC-4 | A run that would cross the cap is refused before any call: `● spend cap reached`, nothing streams | [ ] |
| AC-5 | Delivery phrases masked; the key in no served or committed file | [ ] |
| AC-6 | Stop 1 confirmed | met 2026-09-23, before the build (§§ 2–3) |
| AC-7 | Stop 2 confirmed; the lint green | met 2026-09-23, before the build (§§ 2–3) |
| AC-8 | The rehearsal green before the recording | [ ] |
| AC-9 | One continuous pass per session at 100 %, no zoom; the WebM, the MOV, `chapters.json`, `youtube.md` and the ledger exist | [ ] |
| AC-10 | Every claim in frame true today; `youtube.md` read and true; the recap's figures equal the ledger's; every `{measured}` number measured on the built chat | [ ] |
| AC-11 | The WebM and the MOV stay in `demos/` for the owner to take; nothing uploaded or pushed | [ ] |
| AC-12 | Within the spend budget and the $1.00 cap | [ ] |
| AC-13 | Every action through a real surface; exceptions recorded as findings | [ ] |

**Walked by**: ______  **Date**: ______  **Result**: ______

Signed by the person who walked it, never by the agent that wrote it.
