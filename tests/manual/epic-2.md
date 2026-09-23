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
chat screen (§ 1), which this Epic builds, and the **three stops** of the demo video (§§ 2–4) —
the audience and one sentence, the storyboard, the truth check — ending with the upload. Written
before the build, from the flow PR-1 and the prototype walk records for it, whose control labels and
landings were proven in a browser against the prototype.

> **Every action goes through a real surface.** No direct API call, no database client, no seed
> script. **If something cannot be done from a surface, that is a FINDING** — write it down and
> move on.

> A terminal used to **measure** is allowed, and is named in the step table. A terminal used to
> **achieve** a product outcome is a **FINDING**.

The cold start in § 0 is the operator's job, not the product's, and is exempt. So is the second,
lowered-cap instance in § 1.9: starting a server with a setting is operating it, and what is walked
is the refusal on the page.

## § 0 — Cold start and hazards

**Readiness:** *Epic 1 of 3 built · 1 signed* — this is Epic 2 of 3 in the build order, after the
signed customer chat. It is walked against the dry-walk record of Story 2.4 (local, not published);
any red row there is read out before step 1.1.

> 📍 **Where you are now** — the walk is longer than one sitting, because the agent rehearses and
> records between § 3 and § 4. Your steps, in order: **§ 1** the speed test at 100 (about ten
> minutes) → **§ 2** confirm the audience → **§ 3** confirm the storyboard → *(the agent rehearses
> and records — you are not needed)* → **§ 4** watch the cut, rule on each claim, upload. Each
> section starts from the state its preconditions name, so a pause costs one section, not the walk.

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
| Every speed-test message is a paid call to Jev | **100 ≈ $0.016; 1,000 ≈ $0.163.** The walker only ever starts **100**. The 1,000 run happens once, in the agent's recording, and only with $0.17 of room left under the $1.00 cap |
| The upload to YouTube and a push to GitHub are public | The owner's accounts and the owner's hands only (§ 4.6–4.7). The agent never pushes and never touches YouTube |
| Jev's API can time out or return empty answers under load | In the speed test they are **counted as errors** on the status line, never retried silently; a handful is the designed behaviour, not a finding. A run with more than 1 % errors is a finding |
| The recorded cut is only true for the build it recorded | Any change to `app/` after the recording means re-recording the whole pass; § 4's preconditions check it |

## § 1 — The speed test on the chat screen

**Preconditions as data:** the server on `http://127.0.0.1:8768` has printed its ready line; the
browser shows a fresh session — the greeting is the only bubble, the key-info block reads
`— · ฿0.000 · 0`, no panel rows, no status line above the composer. At least $0.02 of room under
the cap. Nothing listens on 8769.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 1.1 | 👤 🌐 Open the page | `http://127.0.0.1:8768/` | The greeting and its buttons; key-info at zero; the panel header reads `jev-1.13` **legibly**, `● live`, and the rate with its date. `speed test ▾` and `เริ่มใหม่` sit at the top right of the chat and both respond to a click |
| 1.2 | 👤 🌐 Click **speed test ▾** | chat header | A popover: **100 rehearsal** (pressed), **1,000 demo**, **Start**, and a note naming the test set and 32 in flight. Nothing else on the screen changes. No *not wired* text anywhere |
| 1.3 | 👤 🌐 Keep 100, click **Start** | popover | The popover closes. Customer bubbles and Beanly's prepared replies stream **in the chat column**; panel rows stream beside them; the key-info block counts; one line above the composer reads `speed test · n / 100 · s · /s · ✓`. The composer is paused and `speed test ▾` is disabled while it runs. A delivery-details message shows as `[delivery details]`. The whole panel (rows and key-info) is in view |
| 1.4 | 👤 🌐 Wait for the end | the page | The status line holds the summary — `100 answered in … s · …/s · … correct` with the correct share — and **stays**. Elapsed is a few seconds, not a minute: the messages were in flight together, not one after another. At most 40 bubbles and 50 rows on screen. TOTAL TURNS reads 100; AVG RESPONSE and TOTAL COST (about ฿0.5 at a rate near 34) are filled. Errors, if any, are shown on the status line |
| 1.5 | 🤖 💻 Measure: the figures come from the log | `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && python3 -c "import json,glob,os;f=max(glob.glob('var/sessions/*.json'),key=os.path.getmtime);L=json.load(open(f))['log'];u=sum((e.get('jev') or {}).get('cost_usd') or 0 for e in L);print('entries',len(L),'| usd',round(u,6),'| not matched',sum(e['outcome']!='matched' for e in L),'| masked',sum((e.get('input') or {}).get('text')=='[delivery details]' for e in L))"` | `entries 100`; `usd` about 0.016, and `usd × the rate` equals TOTAL COST to the digits shown; `not matched` is a handful; `masked` equals the delivery-details messages in the run (above 0) — no delivery phrase is in the log unmasked |
| 1.6 | 👤 🌐 Click **open** on the newest panel row | the page | The viewer shows a full-catalogue request — every intent in scope and the five entity questions — and the response with its cost in US dollars; the key-info block is not covered. Close it |
| 1.7 | 👤 🌐 Click **เริ่มใหม่** | chat header | The greeting alone; key-info back to zero; no rows; the status line gone |
| 1.8 | 👤 🌐 Type **ค่าส่งเท่าไหร่คะ**, Enter | composer | The prepared shipping answer and one panel row — the chat works as before the run |
| 1.9 | 👤 💻 Start a second, lowered-cap instance in another terminal | `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && PORT=8769 SPEND_CAP_USD=0.001 python3.11 -m app` | `ready · warm-up 200 · http://127.0.0.1:8769` |
| 1.10 | 👤 🌐 On `http://127.0.0.1:8769/`, click **speed test ▾** | the page | **Start is disabled**, and beside it the reason with the room left in the cap; clicking it does nothing — **nothing streams**, no row appears, the key-info block stays at zero, no dialog box. Then Ctrl-C the 8769 terminal |

Notes: 1.5 is run right after 1.4, before 1.7 starts a new session file. The correct count is
scored against the test set's labels; a handful short of 100 is the model's real accuracy on
video, not a defect.

## § 2 — Stop 1: the audience and the one sentence

**Preconditions as data:** Epic 2's Stories are all Done and dry-walked; no storyboard for this
video exists yet, or it exists with its audience block unconfirmed. The chat and the speed test are
the only surfaces the video will show.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 2.1 | 🤖 💬 The readiness table | the agent's reply | One row per chapter source: the customer chat — **built, real**; the speed test — **built, real**. No chapter is drawn from the prototype, so no DESIGN PREVIEW badge is needed |
| 2.2 | 👤 💬 Read and rule: who watches, the three to five ideas, the one sentence they could repeat, the language | the agent's reply | **Confirm** or change, in your words. The audience is developers and AI builders; the chat is Thai and the overlay English. Nothing is drawn until this is confirmed |

## § 3 — Stop 2: the storyboard

**Preconditions as data:** the audience block is confirmed and written at the head of the
storyboard file; no recording of this storyboard exists.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 3.1 | 🤖 💻 The frames drawn, and the lint | the agent's reply; `python3 /Users/dong/src/sales-hive/npc-plugin/plugins/npch/scripts/demo_lint.py /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/demos/*/storyboard.md` | Every chapter drawn as a frame; the lint is green |
| 3.2 | 👤 💬 Read the two sessions | the agent's reply | **Session 1**, a complete chat: a typed sentence at most stages, clicks at least twice. **Session 2**, the speed test at **1,000**, the status line and the key-info block in shot. The panel is in shot in both sessions. Each chapter: what is on screen, what is pointed at, the English subtitle, the idea it lands. The key-info block is in shot in every frame. **Confirm** or change — a change here costs nothing |
| 3.3 | 👤 💬 Check every number a subtitle will say | the agent's reply | Each names where it was measured — on the built chat, not the spikes: latency as the loop measures it (about 500 ms at the median, not the 330–345 ms of the early spikes), throughput and correct share from the dry walk, cost from reported cost at the stated rate |

**Between § 3 and § 4 — the agent's, not walked.** The rehearsal: overlays off, from a cold start,
every planned typed sentence checked for the exit the storyboard expects, the speed test at **100,
never 1,000**; any product defect fixed, not worked around. **A planned sentence Jev misroutes comes back to you**: show it honestly, or choose another sentence — it is never hidden. Then **one continuous recording** — no
resume, no splice — with the speed test at 1,000. The rehearsal is reported as rows with a verdict
each before § 4 starts; a red row means no recording. If Jev becomes unreachable during the
recording, the pass is abandoned and recorded again whole; if the spend cap is reached, recording
stops and you are asked.

## § 4 — Stop 3: the truth check, and the upload

**Preconditions as data:** the video's folder holds the MP4, the WebM, `chapters.json`, the script,
the deck and the ledger; the ledger names the provider (OpenRouter), the model
(`typesafe/jev-1.13`), the rate with its source and date, and the pass's cost; the rehearsal report has no red
row; no commit has touched `app/` since the recording started.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 4.1 | 🤖 💻 Measure: the deliverables exist | `ls -l /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/demos/*/ && ffprobe -v error -show_entries stream=width,height -show_entries format=duration /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/demos/*/*.webm` | Each file with a byte size; `width=1920`, `height=1080`, and a duration that matches `chapters.json`'s last chapter end |
| 4.2 | 👤 🎬 Watch the whole MP4, start to finish | the video file | One continuous pass: session 1 then session 2, no jump. The key-info block is in shot throughout; no chapter card, callout or subtitle covers the chat or a figure |
| 4.3 | 👤 🎬 For each chapter, answer *is this true today?* | the chapter list with its drive column, beside the video | Every claim **yes**, and every English subtitle says what the Thai screen says. A **no** becomes a re-worded subtitle, a label, or a cut chapter — and any change to the recording means re-recording the whole pass |
| 4.4 | 👤 🎬 Check three things in frame | the video | The panel header's `jev-1.13` is legible; the speed test's summary figures match the ledger's; the rate and date on screen match the ledger's |
| 4.5 | 🤖 💻 Measure: the spend, and the key in no log or recorded result | the ledger and the project's spend line, read out; then `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && python3 -c "import re,subprocess;k=re.search(r'OPENROUTER_API_KEY=(\S+)',open('.env').read()).group(1);print(subprocess.run(['grep','-rl','--exclude-dir=.git','--exclude=.env',k,'.'],capture_output=True,text=True).stdout or 'clean')"` | The pass's cost is in the ledger; the POC's total stays under $1.00; `clean` — now including `var/` and the video's folder |
| 4.6 | 👤 💻 Measure: the repo's default branch holds the running chat and a README that says how to start it, and nothing it should not | `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && git fetch origin && git ls-tree -r --name-only origin/main \| grep -c '^app/' ; git ls-tree -r --name-only origin/main \| grep -cx 'README.md' ; git ls-tree -r --name-only origin/main \| grep -cE '\.(mp4\|webm\|png\|jpg)$\|deck\.html\|^(memory\|prototypes\|spikes\|var)/'` | Three numbers: above 0 · `1` · `0`. The README's start command matches § 0's. If the first is 0, the upload waits: the owner pushes first (the agent does not), or rules that the upload waits for Epic 3 |
| 4.7 | 👤 🌐 Upload the MP4 to YouTube | the owner's YouTube account | The video is up; its description links the repo. The agent does not publish |
| 4.8 | 🤖 💬 Record what was shown | the agent's reply | Who watched, what was shown, and — later — what viewers said, each with the `mm:ss` it refers to |

## Findings

| # | What happened | Where | Severity | → destination |
|---|---|---|---|---|
| | | | | |

Severity: blocked the walk / wrong on screen / cosmetic. Every finding gets a destination before
sign-off. A claim found false **after** the upload is the owner's to correct — the video taken
down or its description corrected; the agent cannot touch YouTube. A blocking finding in § 1 may be fixed and § 1 re-walked from its preconditions. A finding
at § 4 that changes the product or a claim goes back to § 3 (the storyboard) and everything after it
is redone — the recording is never patched.

## Sign-off

| AC | What the walker ruled | ✓ |
|---|---|---|
| AC-1 | The speed test streams as chat on the one screen, with the status line | [ ] |
| AC-2 | Its figures come from the log: count, cost, correct, errors | [ ] |
| AC-3 | The summary stands; start-over clears; the chat works after | [ ] |
| AC-4 | A run that would cross the cap is refused before any call, with the room left | [ ] |
| AC-5 | Delivery phrases masked; the key in no served or committed file | [ ] |
| AC-6 | Stop 1 confirmed | [ ] |
| AC-7 | Stop 2 confirmed; the lint green; every number measured on the built chat | [ ] |
| AC-8 | The rehearsal green before the recording | [ ] |
| AC-9 | One continuous recording; the deliverables and the ledger exist | [ ] |
| AC-10 | Every claim in frame true today | [ ] |
| AC-11 | Uploaded by the owner, with the chat on the default branch | [ ] |
| AC-12 | Within the spend budget and the $1.00 cap | [ ] |
| AC-13 | Every action through a real surface; exceptions recorded as findings | [ ] |

**Walked by**: ______  **Date**: ______  **Result**: ______

Signed by the person who walked it, never by the agent that wrote it.
