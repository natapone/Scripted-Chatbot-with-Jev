// Pure helpers for the demo driver: the storyboard read as data, the run's figures put into words,
// the two sessions' chapter stamps joined, and the upload text and the ledger rendered.
// No I/O and no Playwright here — `storyboard.test.mjs` tests every function in this file.
//
// The storyboard (`demos/<id>/storyboard.md`) is the script the owner confirmed. The driver reads
// from it: the title (`# Storyboard — "…"`), the one sentence (§ 1), the ideas (§ 2, the bold part of
// each numbered line), the step tables of §§ 5–6 (`| 1.2 | click **…** | … |`) and the frames table
// of § 7 (title · on screen · drive · callouts · subtitle · key idea · ~s). A wording change there
// changes the video with no code change.

/** Split one markdown table row into trimmed cells (leading and trailing pipes dropped). */
export function cells(line) {
  const t = line.trim();
  if (!t.startsWith("|")) return null;
  return t.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

/** `` `sel` → text; `sel2` → text2 `` → [{anchor, text}]. */
export function parseCallouts(cell) {
  const out = [];
  const re = /`([^`]+)`\s*→\s*(.+?)(?=;\s*`|$)/g;
  for (let m = re.exec(cell); m; m = re.exec(cell)) out.push({ anchor: m[1].trim(), text: m[2].trim() });
  return out;
}

/** One step's Action cell → what the driver does. Unknown wording is an observation, not an action. */
export function parseAction(action) {
  const a = action.trim();
  let m;
  if ((m = a.match(/^\(if ([^)]+)\)\s*click \*\*(.+?)\*\*/))) return { kind: "click", label: m[2], optional: true, when: m[1] };
  if ((m = a.match(/^click \*\*open\*\* on that row/))) return { kind: "open-row" };
  if ((m = a.match(/^click \*\*(.+?)\*\*/))) return { kind: "click", label: m[1], optional: false };
  if ((m = a.match(/^type \*\*(.+?)\*\*/))) return { kind: "type", text: m[1] };
  if (/^press Escape/i.test(a)) return { kind: "key", key: "Escape" };
  if ((m = a.match(/^open `([^`]+)`/))) {
    const u = new URL(m[1]);
    return { kind: "goto", path: u.pathname, run: Number(u.searchParams.get("run")) || 0 };
  }
  if (/the run ends/.test(a)) return { kind: "run-end" };
  if (/the last frame stays/.test(a)) return { kind: "recap" };
  if ((m = a.match(/^hold ~?(\d+)\s*s/))) return { kind: "hold", seconds: Number(m[1]) };
  if (/the end card/.test(a)) return { kind: "end" };
  if (/nothing clicked\)\s*watch/.test(a)) return { kind: "watch" };
  return { kind: "none" };
}

/** The storyboard file → { title, sentence, ideas, chapters }. Throws when § 7 has no rows. */
export function parseStoryboard(md) {
  const lines = md.split("\n");
  const title = (md.match(/^# Storyboard — "(.+?)"/m) || [])[1] || "";
  const sentence = (md.match(/one sentence[^—]*—\s*\*"(.+?)"\*/i) || [])[1] || "";

  const ideas = {};
  const s2 = md.indexOf("## 2.");
  if (s2 >= 0) {
    for (const l of md.slice(s2).split("\n").slice(1)) {
      if (l.startsWith("## ")) break;
      const m = l.match(/^(\d+)\.\s+\*\*(.+?)\*\*/);
      if (m) ideas[Number(m[1])] = m[2].trim();
    }
  }

  const steps = {};
  for (const l of lines) {
    const c = cells(l);
    if (!c || c.length < 3) continue;
    const m = c[0].match(/^(\d+)\.(\d+)$/);
    if (!m) continue;
    const n = Number(m[1]);
    (steps[n] ||= []).push({ id: c[0], action: c[1], expect: c[2], does: parseAction(c[1]) });
  }

  const chapters = [];
  const s7 = md.indexOf("## 7.");
  if (s7 >= 0) {
    for (const l of md.slice(s7).split("\n").slice(1)) {
      if (l.startsWith("## ")) break;
      const c = cells(l);
      if (!c || c.length < 8 || !/^\d+$/.test(c[0])) continue;
      const n = Number(c[0]);
      chapters.push({
        n, title: c[1], onScreen: c[2], drive: c[3], callouts: parseCallouts(c[4]), subtitle: c[5],
        idea: ideas[Number(c[6])] || "", ideaNo: Number(c[6]), seconds: Number(c[7]) || null,
        steps: steps[n] || [],
      });
    }
  }
  if (!chapters.length) throw new Error("storyboard § 7 has no frames");
  return { title, sentence, ideas, chapters };
}

// ---------------------------------------------------------------- numbers into words

export const int = (n) => Math.round(n).toLocaleString("en-US");
export const fix = (n, d) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const WORDS = { 1000: "A thousand", 100: "A hundred" };

/** The storyboard is written for the recording at 1,000. At another size (the proof and the
 *  rehearsal at 100) the literal run size in a title or subtitle is replaced by the size that ran,
 *  so no frame claims calls that were not made. At 1,000 the text is returned unchanged. */
export function sizeWords(text, calls) {
  if (!text || calls === 1000) return text;
  let t = text.replace(/\b1,000\b/g, int(calls));
  if (WORDS[calls]) t = t.replace(/\bA thousand\b/g, WORDS[calls]).replace(/\ba thousand\b/g, WORDS[calls].toLowerCase());
  return t;
}

/** Fill each `{measured}` slot, in order, from `values`. Refuses a slot left over, or a value spare. */
export function fillMeasured(text, values) {
  const slots = (text.match(/\{measured\}/g) || []).length;
  if (slots !== values.length) throw new Error(`${slots} {measured} slot(s) in "${text}", ${values.length} value(s) given`);
  let i = 0;
  return text.replace(/\{measured\}/g, () => String(values[i++]));
}

/** The recap's figures as the card shows them — each read from the server's recap, none typed.
 *  The average and the total are rounded as the page's key-info block rounds them (to 10 ms; ฿ to
 *  3 places), so the card and key-info never show two figures for one fact in the same frame. */
export function recapFigures(r) {
  const need = ["calls", "elapsed_ms", "calls_per_s", "avg_jev_ms", "correct_share", "total_thb", "total_usd",
                "cost_per_call_thb", "cost_per_call_usd"];
  const missing = need.filter((k) => typeof r?.[k] !== "number" || !Number.isFinite(r[k]));
  if (missing.length) throw new Error(`the recap has no ${missing.join(", ")}`);
  const f = [
    { key: "calls", label: "calls", value: int(r.calls) },
    { key: "time", label: "total time", value: `${fix(r.elapsed_ms / 1000, 1)} s` },
    { key: "rate", label: "calls / s", value: fix(r.calls_per_s, 1) },
    { key: "avg", label: "avg server time", value: `${int(Math.round(r.avg_jev_ms / 10) * 10)} ms` },
    { key: "correct", label: "correct", value: `${fix(r.correct_share * 100, 1)} %` },
    { key: "total", label: "total cost", value: `฿${fix(r.total_thb, 3)} ($${fix(r.total_usd, 4)})` },
    { key: "per", label: "per call", value: `฿${fix(r.cost_per_call_thb, 4)}` },
  ];
  if (typeof r.avg_input_tokens === "number") {
    const out = typeof r.avg_output_tokens === "number" ? ` + ${int(r.avg_output_tokens)}` : "";
    f.push({ key: "tokens", label: "tokens / call", value: `${int(r.avg_input_tokens)}${out}` });
  }
  return f;
}

/** The {measured} values chapters 4 and 5 need, from the recap: [seconds] and [seconds, baht]. */
export function measuredFor(chapterSubtitle, r) {
  const slots = (chapterSubtitle.match(/\{measured\}/g) || []).length;
  const secs = fix(r.elapsed_ms / 1000, 1), baht = fix(r.total_thb, 3);   // ฿ as key-info shows it
  return [secs, baht].slice(0, slots);
}

// ---------------------------------------------------------------- chapters

export const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

/** Two sessions' `chapters.json` → one, session 2's stamps offset by session 1's probed duration.
 *  `seconds` is re-derived so the last chapter of session 1 runs to the join. */
export function mergeChapters(sessions) {
  const chapters = [];
  let offset = 0;
  for (const s of sessions) {
    for (const c of s.chapters) chapters.push({ ...c, t: Number((c.t + offset).toFixed(2)), session: s.session });
    offset += s.duration;
  }
  const duration = Number(offset.toFixed(2));
  chapters.forEach((c, i) => {
    c.seconds = Number(((chapters[i + 1]?.t ?? duration) - c.t).toFixed(2));
    c.mmss = mmss(c.t);
  });
  return { duration, chapters };
}

// ---------------------------------------------------------------- the upload text (Thai)

const TH_TITLES = {
  "One Thai sales chat": "แชทขายภาษาไทยหนึ่งบทสนทนา",
  "Every decision on screen": "ทุกการตัดสินใจอยู่บนจอ",
  "What a whole order costs": "ออเดอร์หนึ่งออเดอร์ใช้เงินเท่าไหร่",
  "A thousand chats at once": "พันแชทพร้อมกัน",
  "A hundred chats at once": "ร้อยแชทพร้อมกัน",
  "A thousand calls, in numbers": "หนึ่งพันครั้ง เป็นตัวเลข",
  "A hundred calls, in numbers": "หนึ่งร้อยครั้ง เป็นตัวเลข",
};

/** `youtube.md`, in Thai: title, description, the chapter list (from the merged chapters — the first
 *  line is 0:00 as YouTube requires, the rest are the stamps), and tags. Every figure is read. */
export function renderYoutube({ sentence, chapters, recap, chat, model, rateDate, thbPerUsd }) {
  const r = recap;
  const secs = fix(r.elapsed_ms / 1000, 1);
  const lines = chapters.map((c, i) => {
    const th = TH_TITLES[c.title];
    return `${i === 0 ? "0:00" : c.mmss} ${th ? `${th} (${c.title})` : c.title}`;
  });
  const title = `Jev คุมแชทขายภาษาไทยทั้งบทสนทนา — ${int(r.calls)} แชทใน ${secs} วินาที`;
  const desc = [
    ...(sentence ? [`"${sentence}"`, ""] : []),
    `เดโมจริงของ Jev (${model}) บน OpenRouter: บอทขายเมล็ดกาแฟ "Beanly" ตอบลูกค้าเป็นภาษาไทย ทุกคำตอบเตรียมไว้ล่วงหน้า`,
    `Jev ไม่ได้เขียนคำตอบเอง แต่เลือกขั้นต่อไป (intent และค่าที่ลูกค้าบอก) จากแคตตาล็อกทั้งชุดในการเรียกครั้งเดียว`,
    "",
    `ในคลิปนี้:`,
    `• แชทหนึ่งบทสนทนาตั้งแต่ทักทายจนยืนยันออเดอร์ — ${chat.typedTurns} ข้อความที่พิมพ์ ทุกข้อความ Jev เป็นผู้ตัดสิน รวมทั้งบทสนทนา ฿${fix(chat.totalThb, 3)}`,
    `• ทุกการตัดสินใจแสดงบนจอ: intent ความมั่นใจ เวลา (ms) และค่าใช้จ่ายเป็นบาท พร้อมคำขอที่ส่งไปจริง`,
    `• ทดสอบความเร็ว ${int(r.calls)} แชท ครั้งละ ${int(r.concurrency)} แชทพร้อมกัน เสร็จใน ${secs} วินาที (${fix(r.calls_per_s, 1)} ครั้งต่อวินาที)`,
    `• เวลาประมวลผลเฉลี่ยฝั่งเซิร์ฟเวอร์ ${int(r.avg_jev_ms)} ms · ตอบถูก ${fix(r.correct_share * 100, 1)} % · รวม ฿${fix(r.total_thb, 2)} ($${fix(r.total_usd, 4)}) · ครั้งละ ฿${fix(r.cost_per_call_thb, 4)}`,
    "",
    `ทุกตัวเลขอ่านจากการรันจริงในคลิป ไม่ได้พิมพ์ใส่เอง อัตราแลกเปลี่ยน ฿${fix(thbPerUsd, 2)} ต่อ $1 ณ วันที่ ${rateDate}`,
    `ข้อมูลลูกค้าในคลิปเป็นข้อมูลสมมติทั้งหมด`,
  ];
  const tags = ["Jev", "OpenRouter", "chatbot", "แชทบอท", "ภาษาไทย", "intent classification", "LLM",
                "sales chatbot", "บอทขายของ", "AI", "demo"];
  return [
    `# YouTube — ข้อความสำหรับอัปโหลด`, "",
    `## ชื่อคลิป`, "", title, "",
    `## คำอธิบาย`, "", ...desc, "",
    `## ช่วงเวลา (จาก chapters.json)`, "", ...lines, "",
    `## แท็ก`, "", tags.join(", "), "",
  ].join("\n");
}

/** `ledger.md`: every chapter with its stamp, the assertions, the model and route, the pass's cost. */
export function renderLedger({ mode, recorded, chapters, duration, sessions, recap, chat, model, route,
                               rateDate, thbPerUsd, rateSource, assertions, files }) {
  const r = recap;
  const L = [];
  L.push(`# Ledger — ${mode}`, "", `Recorded ${recorded}. Written by the driver; nothing in it is typed by hand.`, "");
  L.push(`| | |`, `|---|---|`,
         `| model | \`${model}\` |`, `| provider · route | OpenRouter · \`POST https://openrouter.ai${route}\` (via the local server) |`,
         `| rate | ฿${thbPerUsd} per $1, dated ${rateDate} — source: ${rateSource} |`,
         `| video | ${duration.toFixed(2)} s (ffprobe) |`, "");
  L.push(`## Chapters`, "", `| # | title | session | t | mm:ss | seconds |`, `|---|---|---|---|---|---|`);
  for (const c of chapters) L.push(`| ${c.n} | ${c.title} | ${c.session} | ${c.t} | ${c.mmss} | ${c.seconds} |`);
  L.push("", `## Sessions`, "", `| session | port | VAR_DIR | query | duration | cost |`, `|---|---|---|---|---|---|`);
  for (const s of sessions) L.push(`| ${s.session} | ${s.port} | \`${s.varDir}\` | \`${s.query}\` | ${s.duration} s | $${s.costUsd.toFixed(6)} |`);
  L.push("", `## The chat (session 1)`, "",
         `${chat.typedTurns} typed turns, ${chat.answered} answered by Jev, $${chat.totalUsd.toFixed(6)} (฿${fix(chat.totalThb, 4)}).`, "");
  if (chat.path?.length) {
    L.push(`| step | did | intent | value · response |`, `|---|---|---|---|`);
    for (const p of chat.path) L.push(`| ${p.id} | ${p.did} | ${p.intent || ""} | ${p.note || ""} |`);
    L.push("");
  }
  L.push(`## The run (session 2) — the server's recap, raw`, "", "```json", JSON.stringify(r, null, 2), "```", "");
  L.push(`## Cost of the pass`, "",
         `session 1 $${sessions[0].costUsd.toFixed(6)} + session 2 $${sessions[1].costUsd.toFixed(6)} + two server warm-ups ` +
         `(about $0.0000194 each, measured in Story 2.3; not in the turn log) = **$${(sessions[0].costUsd + sessions[1].costUsd + 2 * 0.0000194).toFixed(6)}**`, "");
  L.push(`## Assertions`, "", ...assertions.map((a) => `- ${a.ok ? "PASS" : "FAIL"} — ${a.what}${a.value != null ? ` — ${a.value}` : ""}`), "");
  if (files?.length) L.push(`## Files`, "", ...files.map((f) => `- \`${f.name}\` — ${f.bytes} bytes`), "");
  return L.join("\n");
}
