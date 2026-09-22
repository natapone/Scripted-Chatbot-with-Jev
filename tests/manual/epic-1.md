---
type: walk
id: walk-epic-1
status: draft — written with the Epic, before any code
owner: Natapone Charsombut
updated: 2026-09-22
---

# Epic 1 — Customer walks CU-1

## Read this first

The walker is the **owner**, as the customer. **This is a chat test only** (owner ruling): the speed
test belongs to Epic 2, the video, and is not walked here. Written before the build, from the flow page
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
  `/Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev/.env` **without printing it**. It also runs
  the two measurements below (0.a, 0.b) and reads them out.
* **You run, in your own terminal**:
  `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && python3.11 -m app` *(the exact command
  is filled by Story 1.1; this is the shape)*. It refuses to start without a key, makes its warm-up
  call, and prints the local address.
* **Ready when**: the terminal prints `ready · warm-up 200 · http://127.0.0.1:8765` (the exact
  line is set by Story 1.1) and the page shows the greeting with three buttons and the key-info
  block at zero.

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 0.a | 🤖 💻 Measure: the repo publishes nothing it should not | `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && git status --short --ignored \| grep -E '^\?\?' ; git check-ignore -v .env var/sessions/probe 2>/dev/null` | No `??` line; `.env` and `var/` reported ignored (NFR1, NFR8, NFR10) |
| 0.b | 🤖 💻 Measure: the key is in no served or committed file | `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && python3 -c "import re,subprocess;k=re.search(r'OPENROUTER_API_KEY=(\S+)',open('.env').read()).group(1);print(subprocess.run(['grep','-rl','--exclude-dir=.git','--exclude=.env','--exclude-dir=var',k,'.'],capture_output=True,text=True).stdout or 'clean')"` | `clean` (AC-8) |

| Hazard | What goes wrong |
|---|---|
| Every typed turn is a paid call to Jev | About 16 typed turns in this walk ≈ $0.003 against the owner's $1.00 cap |
| Jev unreachable (E-002), the spend cap, expiry | Not walked by the owner. Proven by the agent in Story 1.6's rehearsal — a dead address for one turn, a lowered cap, a shortened timeout — recorded in the dry-walk file. Stated here so they are not mistaken for walked |
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
| 1.9 | 🤖 💻 Measure: the address is held only in `delivery_text` — not in the log, not in any request | `cd /Users/dong/src/gig_demo/Scripted-Chatbot-with-Jev && python3 -c "import json,glob,os;f=max(glob.glob('var/sessions/*.json'),key=os.path.getmtime);d=json.load(open(f));a=d['order']['delivery_text'];s=json.dumps(d['log'],ensure_ascii=False);print('delivery_text set:',bool(a),'| in log:',(a[:12] in s) if a else None,'| masked entries:',s.count('[delivery details]'))"` | `delivery_text set: True \| in log: False \| masked entries: 1` (NFR10). The agent runs it; the walker does not retype the address |
| 1.10 | 👤 🌐 Click **ยืนยัน** | the page | Order code `BEAN-YYMM-####`; only **เริ่มใหม่** live. Key-info: **AVG RESPONSE** a few hundred ms, **TOTAL COST** ≈ 4 turns × $0.000165 × the rate, **TOTAL TURNS** 10. The panel header shows `jev-1.13`, `● live`, and the rate with its date (FR13, FR14, NFR3) |
| 1.11 | 👤 🌐 Click **open** on the newest panel row | the page | The viewer: what was sent (`shop_said`, `customer_said`, `awaiting`, `history`), what came back (with `t_sent → t_received` to the millisecond), what the bot did. **It does not cover the key-info block** |
| 1.12 | 👤 🌐 Reload the page | browser | **The same conversation is back** — transcript, dead buttons, rows, key-info unchanged (FR25) |
| 1.13 | 🤖 💻 then 👤 🌐 Stop the server (Ctrl-C in its terminal), start it again with the same command, reload | terminal, browser | **The same conversation is back from its snapshot** — the restart half of FR25 |

## § 2 — The customer leads: one sentence

**Preconditions as data:** a fresh session — reached by **typing** `เริ่มใหม่` (the intent, FR9), not the button.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 2.1 | 👤 🌐 Type **เอาเอสเปรสโซ่คั่วเข้ม 3 ถุง เก็บปลายทางนะครับ** | composer | One row with three values: product KBN-002, quantity 3, payment cod. Beanly echoes them and offers the promotion that fits |
| 2.2 | 👤 🌐 Type **ไม่ครับ** | composer | Beanly skips straight to delivery details |
| 2.3 | 👤 🌐 Click **ใช้ข้อมูลตัวอย่าง** | the page | Read-back: 3 × 380 + 100 shipping + 30 COD = **1,270** |
| 2.4 | 👤 🌐 Type **โอเคครับ เอาตามนี้เลย** | composer | Order code — four typed turns |
| 2.5 | 👤 🌐 Click **เริ่มใหม่**, then click **มีโปรอะไรบ้าง** | the page | The four promotions listed, no model call; then click **ดูเมล็ดทั้งหมด** → the three roasters (FR2's other two greeting buttons) |

## § 3 — A question in the middle, and a change at the end

**Preconditions as data:** a fresh session (click **เริ่มใหม่**).

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 3.0 | 👤 🌐 Type **ช่วยแนะนำหน่อยค่ะ**, then **ดริปค่ะ**, then **คั่วอ่อน** | composer | Beanly asks brew, then roast — the lead in the SOP's order (FR2) — then recommends **เกอิชา** and **วอชด์ อาราบิก้า** (filter + light) |
| 3.1 | 👤 🌐 Type **ตัวแรกค่ะ**, then **เอาค่ะ** | composer | The Geisha card; then the quantity question. `เอาค่ะ` is a `matched affirm` — not a fallback |
| 3.2 | 👤 🌐 Type **ค่าส่งเท่าไหร่คะ** | composer | The prepared shipping answer, **then the quantity question again**; the order unchanged |
| 3.3 | 👤 🌐 Type **1 ถุงค่ะ** | composer | Row `inform · by state (awaiting quantity)`, quantity 1 on the Geisha line — provenance says the product came from context. The Geisha + Natural Anaerobic promotion is offered |
| 3.4 | 👤 🌐 Type **ตอนนี้สั่งอะไรไปบ้างคะ** | composer | `view_order`: the order so far — one Geisha line — and the quantity is not re-asked (FR24) |
| 3.4b | 👤 🌐 Click the promotion, click **เก็บเงินปลายทาง**, click **ใช้ข้อมูลตัวอย่าง** | the page | Read-back with two lines, the 80-baht discount, COD fee |
| 3.5 | 👤 🌐 Type **ขอเปลี่ยนเป็น 3 ถุงค่ะ** | composer | The **Geisha** line becomes 3 — no new line; the order is read back again with the new total |
| 3.5b | 👤 🌐 Type **เดี๋ยวก่อนนะ ขอคิดดูก่อน** | composer | `deny` under the read-back: Beanly asks what to change, without pressing; the order stands (CU-1's hesitation branch) |
| 3.6 | 👤 🌐 Click **ยืนยัน** | the page | Order code |

## § 4 — When Jev does not understand

**Preconditions as data:** a fresh session.

`Executed: [ ]  ·  Result: [ ]`

| Step | Action | Command / Where | Expected |
|---|---|---|---|
| 4.1 | 👤 🌐 Type **มีหน้าร้านไหมคะ** | composer | A **FALLBACK** row (intent `none` or a low-confidence pick, shown); Beanly apologises and shows the same buttons; nothing else changes |
| 4.2 | 👤 🌐 Type **รับสมัครพนักงานไหมครับ** | composer | The second apology and the help buttons |
| 4.3 | 👤 🌐 Type **เอาเฮาส์เบลนด์ 2 ถุงค่ะ**, then **ยกเลิกออเดอร์ค่ะ** | composer | A line is added, then `cancel_order` clears it: Beanly confirms, no order remains, the greeting-style buttons return (FR24) |

## Findings

| # | Step | What happened | Class | Routed to |
|---|---|---|---|---|

## Sign-off

`Walked: [ ]  ·  by: ______  ·  date: ______  ·  Result: ______`
