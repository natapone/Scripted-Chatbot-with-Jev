---
type: walk
id: walk-epic-1
status: draft — written with the Epic, before any code
owner: Natapone Charsombut
updated: 2026-09-22
---

# Epic 1 — Customer walks CU-1

## Read this first

The walker is the **owner**, as the customer. Written before the build, from the flow page
[[CU-1]] and the Loop 2c walk records (`prototypes/walks/`), whose control labels and landings were
proven in a browser against the prototype.

> **Every action goes through a real surface.** No direct API call, no database client, no seed
> script. **If something cannot be done from a surface, that is a FINDING** — write it down and
> move on.

> A terminal used to **measure** is allowed, and is named in the step table. A terminal used to
> **achieve** a product outcome is a **FINDING**.

## § 0 — Cold start and hazards

**Readiness:** *Epic 0 of 3 built · 0 signed* — this is Epic 1 of 3, the first; no dry-walk record
exists yet (the dry-walk result file under `memory/project/results/` is written by the build).

The cold start is taken from `memory/product/profile.md` § Cold start **once the build fills it**;
until then this section names what the build must make true. Paths are absolute.

* **Agent runs**: nothing destructive — the app has no database. It deletes
  `/Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/var/sessions/*` (session snapshots; nothing
  else lives there) and confirms `OPENROUTER_API_KEY` is present in
  `/Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/.env` **without printing it**.
* **You run, in your own terminal**:
  `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && python3.11 -m app` *(the exact command
  is filled by Story 1.1; this is the shape)*. It refuses to start without a key, makes its warm-up
  call, and prints the local address.
* **Ready when**: the terminal prints `ready · warm-up 200 · http://127.0.0.1:8765` (the exact
  line is set by Story 1.1) and the page shows the greeting with three buttons and the key-info
  block at zero.

| Hazard | What goes wrong |
|---|---|
| Every typed turn and every speed-test message is a paid call to Jev | Spend counts against the owner's $1.00 cap; a 1,000 run costs about $0.16. § 5 at 100 costs about $0.016 |
| The speed test at 1,000 | Only when the owner says so; § 5 runs at **100** |
| Jev's API can return empty answers (S-3 saw 57 in a row) | The turn shows MODEL FAILED and nothing else changes; that is the designed behaviour, not a finding — unless the order changed |

## § 1 — The bot leads: greeting to a confirmed order

**Preconditions as data:** a fresh session — the greeting is the only bubble, the key-info block
reads `— · ฿0.000 · 0`, no panel rows.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 1.1 | 👤 🌐 Click **ช่วยแนะนำหน่อย** | the page | Your click echoed with *clicked · no model call*; Beanly asks how you brew; four buttons. No panel row |
| 1.2 | 👤 🌐 Type **ทำลาเต้ที่บ้านค่ะ ชอบคั่วกลาง**, Enter | composer | Composer shows *Beanly กำลังคิด…* then a row: `inform`, values `brew espresso_milk · roast medium`, a confidence, ms, ฿ and $. Beanly recommends two products, story first; buttons name them |
| 1.3 | 👤 🌐 Type **ตัวแรกค่ะ** | composer | The card of the **first** product Beanly named; row `select_option` with the product; if Jev did not name it, a provenance line says where it came from |
| 1.4 | 👤 🌐 Click **เอาตัวนี้** | the page | Beanly asks how many bags; buttons 1 · 2 · 3 · 5 ถุง |
| 1.5 | 👤 🌐 Click **2 ถุง** | the page | If a promotion fits (House Blend → 30 baht off at 6): offered once with *ไม่ urgent น้า*; otherwise the payment question |
| 1.6 | 👤 🌐 Click **ไม่เป็นไร เอาเท่าเดิม** (if offered) | the page | Beanly states the shipping fee and asks how to pay |
| 1.7 | 👤 🌐 Type **โอนเอาค่ะ** | composer | Row `inform · payment transfer`; Beanly asks for name, address, phone and says made-up details are fine |
| 1.8 | 👤 🌐 Type a fictional name, address and phone | composer | The read-back shows **your text**; the panel row reads `[delivery details]`; the order table has one line, shipping, total in bold |
| 1.9 | 👤 💻 Measure: the snapshot file holds the address and the log does not | `grep -c "delivery" /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/var/sessions/*.json` and `grep -c "<the street you typed>" /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/var/sessions/*.json` | The first ≥ 1 (the log's masked entries); the second exactly 1 (`delivery_text`) |
| 1.10 | 👤 🌐 Click **ยืนยัน** | the page | Order code `BEAN-YYMM-####`; only **เริ่มใหม่** live; key-info shows the turn count and a total cost around ฿0.02 |
| 1.11 | 👤 🌐 Click **open** on the newest panel row | the page | The viewer: what was sent (`shop_said`, `customer_said`, `awaiting`, `history`), what came back (with `t_sent → t_received` to the millisecond), what the bot did. **It does not cover the key-info block** |
| 1.12 | 👤 🌐 Reload the page | browser | **The same conversation is back** — transcript, dead buttons, rows, key-info unchanged (FR25) |

## § 2 — The customer leads: one sentence

**Preconditions as data:** a fresh session (click **เริ่มใหม่**).

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 2.1 | 👤 🌐 Type **เอาเอสเปรสโซ่คั่วเข้ม 3 ถุง เก็บปลายทางนะครับ** | composer | One row with three values: product KBN-002, quantity 3, payment cod. Beanly echoes them and offers the promotion that fits |
| 2.2 | 👤 🌐 Type **ไม่ครับ** | composer | Beanly skips straight to delivery details |
| 2.3 | 👤 🌐 Click **ใช้ข้อมูลตัวอย่าง** | the page | Read-back: 3 × 380 + 100 shipping + 30 COD = **1,270** |
| 2.4 | 👤 🌐 Type **โอเคครับ เอาตามนี้เลย** | composer | Order code — four typed turns |

## § 3 — A question in the middle, and a change at the end

**Preconditions as data:** a fresh session.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 3.1 | 👤 🌐 Type **เกอิชาถุงละเท่าไหร่คะ**, then **เอาค่ะ** | composer | The price; then the quantity question. `เอาค่ะ` is a `matched affirm` — not a fallback |
| 3.2 | 👤 🌐 Type **ค่าส่งเท่าไหร่คะ** | composer | The prepared shipping answer, **then the quantity question again**; the order unchanged |
| 3.3 | 👤 🌐 Type **1 ถุงค่ะ** | composer | Row `inform · by state (awaiting quantity)`, quantity 1 on the Geisha line — provenance says the product came from context. The Geisha + Natural Anaerobic promotion is offered |
| 3.4 | 👤 🌐 Click the promotion, click **เก็บเงินปลายทาง**, click **ใช้ข้อมูลตัวอย่าง** | the page | Read-back with two lines, the 80-baht discount, COD fee |
| 3.5 | 👤 🌐 Type **ขอเปลี่ยนเป็น 3 ถุงค่ะ** | composer | The **Geisha** line becomes 3 — no new line; the order is read back again with the new total |
| 3.6 | 👤 🌐 Click **ยืนยัน** | the page | Order code |

## § 4 — When Jev does not understand, and when it is unreachable

**Preconditions as data:** a fresh session.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 4.1 | 👤 🌐 Type **มีหน้าร้านไหมคะ** | composer | A **FALLBACK** row (intent `none` or a low-confidence pick, shown); Beanly apologises and shows the same buttons; nothing else changes |
| 4.2 | 👤 🌐 Type **รับสมัครพนักงานไหมครับ** | composer | The second apology and the help buttons |
| 4.3 | 🤖 💻 Agent breaks the model address for one turn | the server's `--jev-url` override, or an env var, as Story 1.2 defines it | *(the walker does not do this; the agent does, on the walker's say-so)* |
| 4.4 | 👤 🌐 Type anything | composer | A **MODEL FAILED · HTTP …** row at ฿0; Beanly says it cannot reach the model; every button still works; key-info shows `● unreachable` |
| 4.5 | 👤 🌐 Click any live button | the page | Works |
| 4.6 | 🤖 💻 Agent restores the address; 👤 types again | composer | A normal row; the `unreachable` line is gone |

## § 5 — The speed test, at 100

**Preconditions as data:** a fresh session. **Target 100** — the owner's rule for rehearsal;
1,000 only when the owner says so.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 5.1 | 👤 🌐 Click **speed test ▾** | header | A popover: **100 rehearsal** preselected · 1,000 demo · Start. The screen otherwise unchanged |
| 5.2 | 👤 🌐 Click **Start** | popover | Messages stream **as chat** — customer bubbles and Beanly's replies — with panel rows beside them; a status line above the composer counts; the key-info block counts. It looks like the chat, very fast |
| 5.3 | 👤 🌐 Watch it finish | the page | Under about 3 s; the status line holds `100 answered in … · …/s · … correct · ฿…`; key-info at 100 turns and about ฿0.6 |
| 5.4 | 👤 💻 Measure: every one of the 100 is in the log with millisecond timestamps | `python3 -c "import json,glob; d=json.load(open(sorted(glob.glob('/Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/var/sessions/*.json'))[-1])); print(len(d['log']), d['log'][-1]['jev']['t_sent'], d['log'][-1]['jev']['t_received'])"` | `100`, and two ISO timestamps with milliseconds |
| 5.5 | 👤 🌐 Click **เริ่มใหม่** | header | Greeting; key-info at zero; status line gone |

## Findings

| # | Step | What happened | Class | Routed to |
|---|---|---|---|---|

## Sign-off

`Walked: [ ]  ·  by: ______  ·  date: ______  ·  Result: ______`
