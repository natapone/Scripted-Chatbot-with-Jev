// `node --test tests/demo/storyboard.test.mjs` — the demo driver's pure helpers. Hermetic: the
// storyboard here is an inline fixture, because the real one (`demos/`) is not published.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  cells, parseCallouts, parseAction, parseStoryboard, sizeWords, fillMeasured, recapFigures,
  measuredFor, mmss, mergeChapters, renderYoutube, renderLedger,
} from "./storyboard.mjs";

const FIXTURE = `# Storyboard — "A fictional demo"

## 1. Who watches

* **The one sentence they repeat** — *"It picked the step, fast and cheap."*

## 2. The five ideas — one per chapter

1. **It chooses.** Every reply is prepared.
2. **It holds up at speed.** Many at once.

## 5. Session 1

| # | Action | What should appear |
|---|---|---|
| 1.1 | the page opens, empty | the greeting |
| 1.2 | click **ช่วยแนะนำหน่อย** | a question |
| 1.3 | type **ชอบคั่วกลางค่ะ** | a row |
| 1.4 | click **open** on that row | the viewer |
| 1.5 | press Escape | it closes |
| 1.6 | (if a promotion is offered) click **ไม่เป็นไร** | the payment question |

## 6. Session 2

| # | Action | What should appear |
|---|---|---|
| 2.1 | open \`http://127.0.0.1:8768/?run=1000\` on an empty instance | streaming |
| 2.2 | (nothing clicked) watch | rows |
| 2.3 | the run ends | the stream stops |
| 2.4 | (nothing clicked) the last frame stays | the recap card |
| 2.5 | hold ~15 s | — |
| 2.6 | the end card | the video ends |

## 7. The frames (what the driver and the lint read)

| # | Title | On screen | Drive | Callouts (anchor → text) | Subtitle | Key idea | ~s |
|---|---|---|---|---|---|---|---|
| 1 | One chat | greeting | built | \`.turn:first-child [data-testid$="-ms"]\` → Time and cost; \`[data-testid="viewer-sent"]\` → What was sent | It chooses the next step. | 1 | 45 |
| 2 | A thousand messages at once | ?run=1000 | built | \`[data-testid="total-baht"]\` → The cost of all of them | 1,000 messages in about {measured} seconds. | 2 | 40 |

## 8. The numbers
`;

test("cells splits a table row and ignores prose", () => {
  assert.deepEqual(cells("| a | b `x` | c |"), ["a", "b `x`", "c"]);
  assert.equal(cells("not a row"), null);
});

test("parseCallouts reads anchor → text pairs, selectors with quotes and $ kept whole", () => {
  assert.deepEqual(parseCallouts('`.a [data-testid$="-ms"]` → Time and cost; `#b` → Sent'),
    [{ anchor: '.a [data-testid$="-ms"]', text: "Time and cost" }, { anchor: "#b", text: "Sent" }]);
  assert.deepEqual(parseCallouts("none"), []);
});

test("parseAction maps the storyboard's verbs and leaves observations alone", () => {
  assert.deepEqual(parseAction("click **เมนูนม**"), { kind: "click", label: "เมนูนม", optional: false });
  assert.deepEqual(parseAction("(if a promotion is offered) click **ไม่เป็นไร เอาเท่าเดิม**"),
    { kind: "click", label: "ไม่เป็นไร เอาเท่าเดิม", optional: true, when: "a promotion is offered" });
  assert.deepEqual(parseAction("type **1 ถุงค่ะ**"), { kind: "type", text: "1 ถุงค่ะ" });
  assert.deepEqual(parseAction("click **open** on that row"), { kind: "open-row" });
  assert.deepEqual(parseAction("press Escape"), { kind: "key", key: "Escape" });
  assert.deepEqual(parseAction("open `http://127.0.0.1:8768/?run=1000` on an empty instance"), { kind: "goto", path: "/", run: 1000 });
  assert.deepEqual(parseAction("hold ~15 s"), { kind: "hold", seconds: 15 });
  assert.equal(parseAction("the run ends").kind, "run-end");
  assert.equal(parseAction("(nothing clicked) the last frame stays").kind, "recap");
  assert.equal(parseAction("the end card").kind, "end");
  assert.equal(parseAction("the page opens, empty").kind, "none");
});

test("parseStoryboard reads title, sentence, ideas, frames and each chapter's steps", () => {
  const sb = parseStoryboard(FIXTURE);
  assert.equal(sb.title, "A fictional demo");
  assert.equal(sb.sentence, "It picked the step, fast and cheap.");
  assert.equal(sb.chapters.length, 2);
  const [c1, c2] = sb.chapters;
  assert.equal(c1.title, "One chat"); assert.equal(c1.idea, "It chooses."); assert.equal(c1.seconds, 45);
  assert.equal(c1.callouts.length, 2); assert.equal(c1.steps.length, 6);
  assert.equal(c1.steps[2].does.text, "ชอบคั่วกลางค่ะ");
  assert.equal(c2.idea, "It holds up at speed."); assert.equal(c2.steps[0].does.run, 1000);
  assert.throws(() => parseStoryboard("# nothing"), /no frames/);
});

test("sizeWords rewrites the run size only when a different size ran", () => {
  const s = "1,000 customer messages, 32 at a time, in about {measured} seconds.";
  assert.equal(sizeWords(s, 1000), s);
  assert.equal(sizeWords(s, 100), "100 customer messages, 32 at a time, in about {measured} seconds.");
  assert.equal(sizeWords("A thousand messages at once", 100), "A hundred messages at once");
  assert.equal(sizeWords("A thousand messages, read from the run", 100), "A hundred messages, read from the run");
  assert.equal(sizeWords("A thousand calls, in numbers", 250), "A thousand calls, in numbers");
});

test("fillMeasured fills slots in order and refuses a mismatch", () => {
  assert.equal(fillMeasured("{measured} s, {measured} baht", ["3.2", "0.58"]), "3.2 s, 0.58 baht");
  assert.throws(() => fillMeasured("{measured} s", []), /1 \{measured\} slot/);
  assert.throws(() => fillMeasured("none", ["x"]), /0 \{measured\} slot/);
});

const RECAP = { calls: 100, concurrency: 32, elapsed_ms: 3221.4, calls_per_s: 31.0424, avg_jev_ms: 646.83,
  correct_share: 0.99, total_thb: 0.58059, total_usd: 0.017503458, cost_per_call_thb: 0.0058059,
  cost_per_call_usd: 0.000175, avg_input_tokens: 4167.49, avg_output_tokens: 586.2 };

test("recapFigures shows every ruled figure from the recap, and refuses a missing one", () => {
  const f = Object.fromEntries(recapFigures(RECAP).map((x) => [x.key, x.value]));
  assert.equal(f.calls, "100"); assert.equal(f.time, "3.2 s"); assert.equal(f.rate, "31.0");
  assert.equal(f.avg, "650 ms"); assert.equal(f.correct, "99.0 %");
  assert.equal(f.total, "฿0.581 ($0.0175)"); assert.equal(f.per, "฿0.0058"); assert.equal(f.tokens, "4,167 + 586");
  assert.throws(() => recapFigures({ ...RECAP, avg_jev_ms: null }), /avg_jev_ms/);
});

test("measuredFor gives seconds, then baht, for as many slots as the subtitle has", () => {
  assert.deepEqual(measuredFor("in about {measured} seconds", RECAP), ["3.2"]);
  assert.deepEqual(measuredFor("{measured} s, {measured} baht", RECAP), ["3.2", "0.581"]);
});

test("mergeChapters offsets session 2 by session 1's duration and re-derives seconds", () => {
  const m = mergeChapters([
    { session: 1, duration: 100.5, chapters: [{ n: 1, t: 1.2 }, { n: 2, t: 40 }] },
    { session: 2, duration: 50, chapters: [{ n: 3, t: 0.8 }] },
  ]);
  assert.equal(m.duration, 150.5);
  assert.deepEqual(m.chapters.map((c) => [c.n, c.t, c.seconds, c.mmss, c.session]),
    [[1, 1.2, 38.8, "0:01", 1], [2, 40, 61.3, "0:40", 1], [3, 101.3, 49.2, "1:41", 2]]);
  assert.equal(mmss(61.99), "1:01");
});

test("renderYoutube is Thai, starts at 0:00, uses the stamps after it, and reads every figure", () => {
  const md = renderYoutube({ sentence: "It picked the step, fast and cheap.",
    chapters: [{ title: "One Thai sales chat", mmss: "0:01" }, { title: "A hundred messages at once", mmss: "2:35" }],
    recap: RECAP, chat: { typedTurns: 5, totalThb: 0.0301 }, model: "typesafe/jev-1.13", rateDate: "2026-09-23", thbPerUsd: 33.17,
  });
  assert.match(md, /## ชื่อคลิป/); assert.match(md, /## แท็ก/);
  assert.match(md, /^0:00 แชทขายภาษาไทยหนึ่งบทสนทนา \(One Thai sales chat\)$/m);
  assert.match(md, /^2:35 ร้อยข้อความพร้อมกัน \(A hundred messages at once\)$/m);
  assert.match(md, /^"It picked the step, fast and cheap\."$/m);
  assert.match(md, /100 ข้อความใน 3\.2 วินาที/); assert.match(md, /ทดสอบความเร็ว 100 ข้อความ ครั้งละ 32 ข้อความพร้อมกัน/);
  assert.doesNotMatch(md, /(ใน|ละ) [\d,]+ แชท|[\d,]+ แชทใน/);   // counts are messages, not chats
  // F-28: the average as the recap card and key-info round it (646.83 → 650 ms), never a second figure
  assert.match(md, /เวลาประมวลผลเฉลี่ยฝั่งเซิร์ฟเวอร์ 650 ms/); assert.doesNotMatch(md, /647 ms/);
  const card = Object.fromEntries(recapFigures(RECAP).map((x) => [x.key, x.value]));
  assert.ok(md.includes(`เฉลี่ยฝั่งเซิร์ฟเวอร์ ${card.avg}`)); assert.match(md, /฿0\.58 \(\$0\.0175\)/); assert.match(md, /฿0\.030/);
});

test("renderLedger names the model, the route, the rate and the pass's cost", () => {
  const md = renderLedger({ mode: "proof", recorded: "2026-09-23T00:00:00Z", duration: 150.5,
    chapters: [{ n: 1, title: "x", session: 1, t: 1.2, mmss: "0:01", seconds: 10 }],
    sessions: [{ session: 1, port: 8768, varDir: "/tmp/a", query: "/", duration: 100.5, costUsd: 0.001 },
               { session: 2, port: 8768, varDir: "/tmp/b", query: "/?run=100", duration: 50, costUsd: 0.0175 }],
    recap: RECAP, chat: { typedTurns: 5, answered: 5, totalUsd: 0.001, totalThb: 0.033, path: [] },
    model: "typesafe/jev-1.13", route: "/api/v1/systemone", rateDate: "2026-09-23", thbPerUsd: 33.17,
    rateSource: "the owner's .env", assertions: [{ ok: true, what: "1920x1080", value: "yes" }], files: [] });
  assert.match(md, /typesafe\/jev-1\.13/); assert.match(md, /\/api\/v1\/systemone/);
  assert.match(md, /\*\*\$0\.018539\*\*/); assert.match(md, /PASS — 1920x1080 — yes/);
});
