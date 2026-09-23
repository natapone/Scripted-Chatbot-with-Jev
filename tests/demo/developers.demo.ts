/**
 * The recording driver for the developers' demo — "Jev routes a Thai sales chat".
 *
 * Reads the confirmed storyboard (`demos/developers-2026-09-23/storyboard.md`) as data — chapter
 * titles, idea lines, the step tables' clicks and typed sentences, the callouts and the subtitles —
 * and drives the real chat on the real Jev, one continuous pass per session, each from an empty
 * VAR_DIR on its own server process which this driver starts and stops:
 *
 *   session 1 = chapters 1–3, the chat;  session 2 = chapters 4–5, the page opened at `/?run=N`.
 *
 * Chapter 5's recap card and the end card are video overlays drawn from the server's recap
 * (`GET /api/run`), every figure read, none typed. The page is never zoomed (1920×1080, DPR 1).
 *
 * Run (Node 22.18+ for type stripping; Playwright from pw.mjs; ffmpeg/ffprobe on PATH):
 *
 *   node --import ./tests/demo/pw.mjs tests/demo/developers.demo.ts --rehearsal   # overlays off, ?run=100, no video
 *   node --import ./tests/demo/pw.mjs tests/demo/developers.demo.ts --proof       # overlays on,  ?run=100 → <demo>/proof/
 *   node --import ./tests/demo/pw.mjs tests/demo/developers.demo.ts --record      # overlays on,  ?run=1000 → <demo>/
 *
 * Options: `--session 1|2|both` (default both; a lone session 2 assembles the deliverables when the
 * same mode's session 1 is already on disk), `--port 8768`, `--demo demos/developers-2026-09-23`,
 * `--assemble` (rebuild the deliverables from the sessions on disk, no browser, no call).
 *
 * A Jev failure, a timed-out call, a refused run or a run with errors stops the pass whole: the
 * session's video is discarded and nothing is assembled from it. Never resumed, never spliced.
 */
import { spawn, execFileSync, type ChildProcess } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import {
  parseStoryboard, sizeWords, fillMeasured, measuredFor, recapFigures, mergeChapters, renderYoutube,
  renderLedger,
} from './storyboard.mjs';

// ---------------------------------------------------------------- arguments and mode

const argv = process.argv.slice(2);
const flag = (n: string) => argv.includes(n);
const opt = (n: string, d: string) => { const i = argv.indexOf(n); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };

const MODE = flag('--record') ? 'record' : flag('--proof') ? 'proof' : flag('--rehearsal') ? 'rehearsal' : '';
if (!MODE) {
  console.error('choose a mode: --rehearsal (overlays off, ?run=100), --proof (overlays on, ?run=100) or --record (?run=1000)');
  process.exit(2);
}
// The stage reads DEMO_STAGE when it is imported, so the mode is set before the import below.
process.env.DEMO_STAGE = MODE === 'rehearsal' ? '0' : '1';
const { openStage, STAGE_ON } = await import('./stage.ts');
const { chromium } = await import('playwright');

const REPO = path.resolve(import.meta.dirname, '..', '..');
const DEMO = path.resolve(REPO, opt('--demo', 'demos/developers-2026-09-23'));
const ID = path.basename(DEMO);
const OUT = MODE === 'record' ? DEMO : path.join(DEMO, MODE);
const PORT = Number(opt('--port', '8768'));
const RUN_SIZE = MODE === 'record' ? 1000 : 100;
const SESSIONS = opt('--session', 'both');
const PY = process.env.PYTHON || 'python3.11';
const W = 1920, H = 1080;

const sb = parseStoryboard(fs.readFileSync(path.join(DEMO, 'storyboard.md'), 'utf8'));
const CHAPTERS = sb.chapters.length;
const SESSION_OF = (n: number) => (n <= 3 ? 1 : 2);   // storyboard § 5–6: chapters 1–3 chat, 4–5 speed test

/** Where each callout fires: after the step whose result it points at (storyboard §§ 5–7). A callout
 *  with no cue fires after the chapter's last step. The wording stays in the storyboard. */
const CUES: Record<number, string[]> = { 1: ['1.4'], 2: ['2.4', '2.5'], 3: ['3.4'], 4: ['4.2', '4.2'], 5: ['5.1'] };
/** Chapters that open on a sparse frame — the owner accepted 16 px labels there (F-20). */
const SPARSE_OPENING = new Set([1, 2, 3, 4]);

class AbortPass extends Error {}

// ---------------------------------------------------------------- the server, from an empty VAR_DIR

async function startServer(tag: string) {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const varDir = path.join(REPO, 'var', 'demo', `${MODE}-${tag}-${stamp}`);
  fs.mkdirSync(varDir, { recursive: true });
  if (fs.readdirSync(varDir).length) throw new AbortPass(`VAR_DIR ${varDir} is not empty`);
  const child = spawn(PY, ['-m', 'app'], {
    cwd: REPO, env: { ...process.env, PORT: String(PORT), VAR_DIR: varDir }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let out = '';
  const ready = await new Promise<string>((resolve, reject) => {
    const t = setTimeout(() => reject(new AbortPass(`the server printed no ready line in 60 s: ${out.slice(-300)}`)), 60_000);
    const on = (b: Buffer) => {
      out += b.toString();
      const m = out.match(/ready · warm-up (\S+) · (\S+)/);
      if (m) { clearTimeout(t); resolve(m[1]); }
    };
    child.stdout!.on('data', on); child.stderr!.on('data', on);
    child.on('exit', (code) => { clearTimeout(t); reject(new AbortPass(`the server exited (${code}): ${out.slice(-300)}`)); });
  });
  if (ready !== '200') { child.kill('SIGINT'); throw new AbortPass(`the warm-up answered ${ready}, not 200 — the network or Jev is down`); }
  console.log(`[demo] server on ${PORT}, VAR_DIR ${path.relative(REPO, varDir)}, warm-up ${ready}`);
  return { child, varDir, base: `http://127.0.0.1:${PORT}` };
}

async function stopServer(child: ChildProcess) {
  if (child.exitCode !== null) return;
  child.kill('SIGINT');
  await new Promise((r) => { const t = setTimeout(() => { child.kill('SIGKILL'); r(null); }, 5000); child.on('exit', () => { clearTimeout(t); r(null); }); });
}

// ---------------------------------------------------------------- one session

type Assertion = { ok: boolean; what: string; value?: string | number | null };

async function runSession(n: 1 | 2) {
  const dir = path.join(OUT, `session-${n}`);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const assertions: Assertion[] = [];
  const legibility: any[] = [];
  const pathRows: any[] = [];
  let srv: Awaited<ReturnType<typeof startServer>>;
  try { srv = await startServer(`s${n}`); } catch (e: any) {
    fs.writeFileSync(path.join(dir, 'aborted.json'), JSON.stringify({ mode: MODE, session: n, at: new Date().toISOString(), reason: e.message }, null, 2));
    console.error(`[demo] session ${n} ABORTED before the pass — ${e.message}`);
    process.exitCode = 3;
    return null;
  }
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: W, height: H }, deviceScaleFactor: 1,
    ...(STAGE_ON ? { recordVideo: { dir: path.join(dir, '.raw'), size: { width: W, height: H } } } : {}),
  });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('dialog', async (d) => { errors.push(`dialog: ${d.message()}`); await d.dismiss(); });

  const stage = await openStage(page, { lang: 'en', demoDir: dir, chapters: CHAPTERS, subtitleFloor: 4, subtitlePadY: 12 });
  let recap: any = null;
  let aborted: string | null = null;
  const query = n === 1 ? '/' : `/?run=${RUN_SIZE}`;

  const sessionId = () => page.evaluate(() => sessionStorage.getItem('session_id') || '');
  const composerReady = () => page.waitForFunction(() => document.querySelector<HTMLElement>('#composer')?.dataset.state === 'ready', null, { timeout: 90_000 });

  /** One click or typed message, and the server's answer to it. A Jev failure stops the pass. */
  async function turn(act: () => Promise<void>, id: string, did: string) {
    const resp = page.waitForResponse((r) => r.url().endsWith('/api/turn') && r.request().method() === 'POST', { timeout: 90_000 });
    await act();
    const r = await (await resp).json();
    await composerReady();
    const e = r.log_entry || {};
    const lastBot = (r.bot || []).at(-1) || {};
    pathRows.push({ id, did, intent: e.jev?.intent || (e.jev ? '' : 'no model call'), outcome: e.outcome,
                    note: [e.jev ? `${e.jev.confidence ?? ''}`.slice(0, 4) : '', lastBot.response_id || ''].filter(Boolean).join(' · '),
                    bot: (r.bot || []).map((b: any) => b.text).join(' ⏎ ').slice(0, 400),
                    buttons: (lastBot.buttons || []).map((b: any) => b.label), intents_in_scope: e.intents_in_scope,
                    cost_usd: e.jev?.cost_usd ?? 0 });
    if (r.model_status !== 'live' || ['model_failed', 'cap_reached'].includes(e.outcome) || e.jev?.error) {
      throw new AbortPass(`step ${id}: Jev did not answer (${r.model_status}, ${e.outcome}, ${e.jev?.error || ''})`);
    }
    await stage.pause(e.jev ? 2600 : 1400);                    // a hold after each Jev answer, so the row can be read
  }

  const liveButton = (label: string) => page.locator('button.opt[data-live="true"]').filter({ hasText: new RegExp(`^\\s*${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*$`) });

  async function waitRunEnd() {
    const id = await sessionId();
    const deadline = Date.now() + 10 * 60_000;
    for (;;) {
      const p = await (await fetch(`${srv.base}/api/run?session_id=${encodeURIComponent(id)}&since=999999`)).json();
      if (p.state && p.state !== 'running') {
        if (p.state !== 'done') throw new AbortPass(`the run ended ${p.state} (${p.model_status})`);
        recap = p.recap;
        break;
      }
      if (p.error) throw new AbortPass(`the run: ${p.error}`);
      if (Date.now() > deadline) throw new AbortPass('the run did not end in 10 minutes');
      await new Promise((r) => setTimeout(r, 250));
    }
    if (recap.errors || recap.timeouts) throw new AbortPass(`the run had ${recap.errors} error(s), ${recap.timeouts} timeout(s) — retry the pass whole`);
    // The page draws the last answers a poll after the server ends; wait for its TURNS to match.
    await page.waitForFunction((calls) => Number(document.querySelector('#total-turns')?.textContent?.replace(/,/g, '')) >= calls,
                               recap.calls, { timeout: 30_000 }).catch(() => {});
    await composerReady();
    const shown = await page.evaluate(() => ({ turns: document.querySelector('#total-turns')?.textContent,
      baht: document.querySelector('#total-baht')?.textContent, avg: document.querySelector('#avg-ms')?.textContent,
      usd: document.querySelector('[data-testid="key-info"]')?.getAttribute('data-total-usd') }));
    assertions.push({ ok: recap.calls === RUN_SIZE, what: `the run's calls equal the target ${RUN_SIZE}`, value: recap.calls });
    assertions.push({ ok: recap.concurrency === 32, what: 'the subtitle\'s "32 at a time" is the run\'s concurrency', value: recap.concurrency });
    assertions.push({ ok: Math.abs(Number(shown.usd) - recap.total_usd) < 1e-6, what: 'key-info TOTAL COST ($) equals the recap total_usd', value: `${shown.usd} vs ${recap.total_usd}` });
    assertions.push({ ok: Number(String(shown.turns).replace(/,/g, '')) === recap.calls, what: 'key-info TURNS equals the recap calls', value: `${shown.turns}` });
    assertions.push({ ok: true, what: 'key-info as shown at the end of the run', value: `${shown.avg} · ${shown.baht} · ${shown.turns}` });
  }

  async function recapCard() {
    const figs = recapFigures(recap);
    const heading = sizeWords('A thousand calls, read from the run', recap.calls);
    if (!STAGE_ON) return;
    await page.evaluate(({ figs, heading }) => {
      const root = document.getElementById('stage-root'); if (!root) return;
      const card = document.createElement('div'); card.id = 'stage-recap';
      card.style.cssText = 'position:fixed;left:120px;top:150px;width:1000px;box-sizing:border-box;padding:40px 48px;' +
        'background:rgba(11,15,22,.95);color:#fff;border-radius:18px;box-shadow:0 20px 60px rgba(0,0,0,.45);' +
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,system-ui,sans-serif;opacity:0;transition:opacity .4s";
      card.innerHTML = `<div style="font:600 26px/1.2 inherit;color:#fbbf24;letter-spacing:.02em;margin-bottom:28px">${heading}</div>` +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:26px 48px">' +
        figs.map((f: any) => `<div data-recap="${f.key}"><div style="font:500 24px/1.2 inherit;color:#94a3b8">${f.label}</div>` +
          `<div style="font:700 42px/1.2 inherit;margin-top:6px;white-space:nowrap">${f.value}</div></div>`).join('') + '</div>';
      root.appendChild(card);
      requestAnimationFrame(() => { card.style.opacity = '1'; });
    }, { figs, heading });
    await stage.pause(700);
    // What the card shows is what the recap said: read it back off the frame.
    const shown = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#stage-recap [data-recap]')]
      .map((e) => [e.getAttribute('data-recap'), (e.lastElementChild as HTMLElement).innerText])));
    const same = figs.every((f: any) => shown[f.key] === f.value);
    assertions.push({ ok: same, what: 'the recap card shows each figure as formatted from GET /api/run\'s recap', value: figs.map((f: any) => `${f.label} ${f.value}`).join(' · ') });
  }

  async function endCard() {
    if (!STAGE_ON) return;
    await page.evaluate(({ title, sentence }) => {
      const root = document.getElementById('stage-root'); if (!root) return;
      const card = document.createElement('div'); card.id = 'stage-end';
      card.style.cssText = 'position:fixed;inset:0;background:#0b0f16;color:#fff;display:flex;flex-direction:column;' +
        'justify-content:center;align-items:flex-start;padding:0 154px;opacity:0;transition:opacity .4s;' +
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,system-ui,sans-serif";
      card.innerHTML = `<div style="font:700 76px/1.1 inherit;letter-spacing:-.01em">${title}</div>` +
        '<div style="width:180px;height:3px;background:#fbbf24;margin:32px 0"></div>' +
        `<div style="font:400 36px/1.4 inherit;color:#cbd5e1;max-width:30em">“${sentence}”</div>`;
      root.appendChild(card);
      const cur = document.getElementById('stage-cursor'); if (cur) cur.style.display = 'none';
      requestAnimationFrame(() => { card.style.opacity = '1'; });
    }, { title: sb.title, sentence: sb.sentence });
    await stage.pause(5000);
  }

  async function still(name: string) {
    if (!STAGE_ON) return;
    const f = path.join(dir, 'stills', `${name}.png`);
    fs.mkdirSync(path.dirname(f), { recursive: true });
    await page.screenshot({ path: f });
  }

  async function doCallout(c: { anchor: string; text: string }, chapterNo: number, first: boolean) {
    // Above key-info (it is never covered); below a panel row, over the older rows, so the bubble
    // never sits on the row it names; beside the viewer, over the chat.
    const side = /key-info|total-baht/.test(c.anchor) ? 'top' : /viewer/.test(c.anchor) ? 'left' : 'bottom';
    await stage.callout(c.anchor, sizeWords(c.text, RUN_SIZE), { side, poster: first });
  }

  async function checkLegible(where: string) {
    try {
      const m = await stage.legible();
      if (m) { legibility.push({ where, p10: m.p10, n: m.n, zoom: m.zoom }); assertions.push({ ok: true, what: `legible at ${where} (p10 ≥ 20 px, zoom 1, overlays in the safe area)`, value: `p10 ${m.p10} px, n ${m.n}` }); }
    } catch (e: any) {
      legibility.push({ where, error: String(e.message).split('\n')[0] });
      assertions.push({ ok: false, what: `legible at ${where}`, value: String(e.message).split('\n')[0] });
    }
  }

  try {
    await page.goto(`${srv.base}/`);
    await page.waitForSelector('[data-testid^="bot-"]');
    await composerReady();
    const vp = await page.evaluate(() => ({ w: innerWidth, h: innerHeight, dpr: devicePixelRatio, zoom: document.body.style.zoom || '1' }));
    assertions.push({ ok: vp.w === W && vp.h === H && vp.dpr === 1 && vp.zoom === '1', what: 'frame 1920×1080, DPR 1, page zoom 1', value: JSON.stringify(vp) });

    for (const ch of sb.chapters.filter((c: any) => SESSION_OF(c.n) === n)) {
      const title = sizeWords(ch.title, RUN_SIZE);
      await stage.chapter(ch.n, title, ch.idea, { drive: ch.drive === 'prototype' ? 'prototype' : 'built', legible: !SPARSE_OPENING.has(ch.n) });
      const measured = /\{measured\}/.test(ch.subtitle);
      if (!measured) await stage.subtitle(ch.subtitle);
      const cues = CUES[ch.n] || [];
      const pending = ch.callouts.map((c: any, i: number) => ({ c, at: cues[i] || null }));
      let firstCallout = true;
      const fire = async (stepId: string | null) => {
        for (const p of pending.filter((p: any) => p.at === stepId)) { await doCallout(p.c, ch.n, firstCallout); firstCallout = false; }
      };

      for (const st of ch.steps) {
        const d = st.does;
        if (d.kind === 'click') {
          const b = liveButton(d.label);
          if (d.optional) {
            if (!(await b.count())) { pathRows.push({ id: st.id, did: `${d.when}? no — "${d.label}" not offered, skipped` }); await fire(st.id); continue; }
          }
          await b.first().waitFor({ state: 'visible', timeout: 15_000 }).catch(() => { throw new AbortPass(`step ${st.id}: no live button "${d.label}" — the path differs from the storyboard`); });
          await turn(() => stage.humanClick(b), st.id, `click ${d.label}`);
        } else if (d.kind === 'type') {
          const input = page.locator('#composer input');
          await turn(async () => { await stage.humanType(input, d.text); await stage.humanClick(page.locator('#send')); }, st.id, `type ${d.text}`);
        } else if (d.kind === 'open-row') {
          await stage.humanClick(page.locator('[data-testid="panel"] .turn:first-child [data-testid$="-open"]'));
          await page.waitForSelector('[data-testid="viewer"][data-open="true"]', { timeout: 10_000 });
          pathRows.push({ id: st.id, did: 'open the newest row' });
          await stage.pause(1200);
          await checkLegible(`step ${st.id}, the viewer open`);
        } else if (d.kind === 'key') {
          await page.keyboard.press(d.key);
          pathRows.push({ id: st.id, did: `press ${d.key}` });
          await stage.pause(900);
        } else if (d.kind === 'goto') {
          await page.goto(`${srv.base}${d.path}?run=${RUN_SIZE}`);
          pathRows.push({ id: st.id, did: `open ${d.path}?run=${RUN_SIZE}` });
          await page.waitForFunction(() => document.querySelectorAll('[data-testid="panel"] .turn').length > 0, null, { timeout: 60_000 })
            .catch(async () => { const s = await page.locator('#key-status').textContent(); throw new AbortPass(`the run did not start (key-info status: ${s})`); });
          await stage.pause(1500);
          await checkLegible(`step ${st.id}, mid-stream`);
        } else if (d.kind === 'watch') {
          // the callouts cued here point at the stream while it runs
        } else if (d.kind === 'run-end') {
          await waitRunEnd();
          pathRows.push({ id: st.id, did: 'the run ended', note: `${recap.calls} calls, ${(recap.elapsed_ms / 1000).toFixed(1)} s` });
          if (measured) await stage.subtitle(fillMeasured(sizeWords(ch.subtitle, RUN_SIZE), measuredFor(ch.subtitle, recap)));
          await stage.pause(4000);
          await still('ch4-run-end');
        } else if (d.kind === 'recap') {
          if (!recap) throw new AbortPass('no recap to draw');
          await recapCard();
          if (measured) await stage.subtitle(fillMeasured(sizeWords(ch.subtitle, RUN_SIZE), measuredFor(ch.subtitle, recap)));
          await still('ch5-recap');
          pathRows.push({ id: st.id, did: 'the recap card, from GET /api/run' });
        } else if (d.kind === 'hold') {
          await fire(st.id);
          await stage.pause(d.seconds * 1000);
          pathRows.push({ id: st.id, did: `hold ${d.seconds} s` });
          continue;
        } else if (d.kind === 'end') {
          await endCard();
          await still('ch5-end-card');
          pathRows.push({ id: st.id, did: 'the end card' });
          continue;
        }
        await fire(st.id);
      }
      await fire(null);
      if (ch.n === 1) {
        const row = pathRows.find((r) => r.intents_in_scope);
        assertions.push({ ok: row?.intents_in_scope === 26, what: 'the "from 26 intents" callout: intents in scope on the first typed turn', value: row?.intents_in_scope });
      }
      if (ch.n === 3) await checkLegible('the end of chapter 3');
      await stage.pause(2500);
    }

    // session 1's cost and turns from the session's own log
    const sid = await sessionId();
    const v = await (await fetch(`${srv.base}/api/session?id=${encodeURIComponent(sid)}`)).json();
    const log = v.log || [];
    const answered = log.filter((e: any) => e.jev && !['model_failed', 'cap_reached'].includes(e.outcome));
    const costUsd = n === 2 && recap ? recap.total_usd : answered.reduce((a: number, e: any) => a + (e.jev.cost_usd || 0), 0);
    const cfg = await (await fetch(`${srv.base}/api/config`)).json();
    if (errors.length) assertions.push({ ok: false, what: 'no page error, no dialog', value: errors.join(' | ') });
    else assertions.push({ ok: true, what: 'no page error, no dialog' });

    const video = await stage.close(context, `session-${n}.webm`);
    fs.rmSync(path.join(dir, '.raw'), { recursive: true, force: true });
    const stamps = JSON.parse(fs.readFileSync(path.join(dir, 'chapters.json'), 'utf8'));
    const session = {
      session: n, mode: MODE, port: PORT, varDir: path.relative(REPO, srv.varDir), query, runSize: RUN_SIZE,
      stage: STAGE_ON, video: video ? path.basename(video) : null, duration: stamps.duration, durationFrom: stamps.durationFrom,
      costUsd, config: cfg,
      chat: n === 1 ? { typedTurns: log.filter((e: any) => e.input?.kind === 'typed').length, answered: answered.length,
                        totalUsd: costUsd, totalThb: costUsd * cfg.thb_per_usd, path: pathRows } : null,
      path: pathRows, recap, legibility, assertions,
    };
    fs.writeFileSync(path.join(dir, 'session.json'), JSON.stringify(session, null, 2));
    const bad = assertions.filter((a) => !a.ok);
    console.log(`[demo] session ${n} (${MODE}) done — ${pathRows.length} steps, $${costUsd.toFixed(6)}, ${bad.length} failed assertion(s)`);
    for (const a of assertions) console.log(`  ${a.ok ? 'PASS' : 'FAIL'} ${a.what}${a.value != null ? ` — ${a.value}` : ''}`);
    return session;
  } catch (e: any) {
    aborted = e instanceof AbortPass ? e.message : `driver error: ${e?.stack || e}`;
    await context.close().catch(() => {});
    fs.rmSync(dir, { recursive: true, force: true });           // no deliverable from a broken pass
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'aborted.json'), JSON.stringify({ mode: MODE, session: n, at: new Date().toISOString(), reason: aborted, path: pathRows }, null, 2));
    console.error(`[demo] session ${n} ABORTED — ${aborted}`);
    process.exitCode = 3;
    return null;
  } finally {
    await browser.close().catch(() => {});
    await stopServer(srv.child);
  }
}

// ---------------------------------------------------------------- the deliverables

const probe = (f: string) => JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_name,width,height,r_frame_rate',
  '-show_entries', 'format=duration,size', '-of', 'json', f], { encoding: 'utf8' }));

function assemble() {
  const s = [1, 2].map((n) => {
    const f = path.join(OUT, `session-${n}`, 'session.json');
    if (!fs.existsSync(f)) throw new Error(`session ${n} of ${MODE} is not on disk (${path.relative(REPO, f)}) — record it first`);
    return JSON.parse(fs.readFileSync(f, 'utf8'));
  });
  if (!s[1].recap) throw new Error('session 2 carries no recap');
  const files: { name: string; bytes: number }[] = [];
  const assertions = [...s[0].assertions.map((a: any) => ({ ...a, what: `session 1: ${a.what}` })),
                      ...s[1].assertions.map((a: any) => ({ ...a, what: `session 2: ${a.what}` }))];
  let durations = [s[0].duration, s[1].duration];
  let duration = durations[0] + durations[1];

  if (STAGE_ON) {
    const webm = path.join(OUT, `${ID}.webm`), mov = path.join(OUT, `${ID}.mov`);
    const parts = [1, 2].map((n) => path.join(OUT, `session-${n}`, `session-${n}.webm`));
    durations = parts.map((p) => Number(Number(probe(p).format.duration).toFixed(2)));
    // The two passes are joined at the session boundary and nowhere else (storyboard: two sessions).
    // Re-encoded rather than stream-copied: Playwright's WebM carries no reliable timestamps to copy.
    const list = path.join(OUT, '.concat.txt');
    fs.writeFileSync(list, parts.map((p) => `file '${p.replace(/'/g, "'\\''")}'`).join('\n') + '\n');
    execFileSync('ffmpeg', ['-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', list, '-c:v', 'libvpx', '-b:v', '6M',
      '-crf', '10', '-deadline', 'good', '-cpu-used', '4', '-r', '25', '-an', webm], { stdio: 'inherit' });
    fs.rmSync(list);
    execFileSync('ffmpeg', ['-y', '-v', 'error', '-i', webm, '-c:v', 'libx264', '-crf', '20', '-pix_fmt', 'yuv420p', '-an', mov], { stdio: 'inherit' });
    const pw = probe(webm), pm = probe(mov);
    duration = Number(Number(pw.format.duration).toFixed(2));
    for (const [f, p] of [[webm, pw], [mov, pm]] as const) {
      const v = p.streams[0];
      assertions.push({ ok: v.width === W && v.height === H, what: `${path.basename(f)} is ${W}×${H}`, value: `${v.codec_name} ${v.width}×${v.height} ${v.r_frame_rate}, ${Number(p.format.duration).toFixed(2)} s, ${p.format.size} bytes` });
    }
    const sum = durations[0] + durations[1];
    assertions.push({ ok: Math.abs(duration - sum) < 1.0, what: 'the joined WebM runs as long as the two passes', value: `${duration} s vs ${sum.toFixed(2)} s` });
  }

  const merged = mergeChapters([
    { session: 1, duration: durations[0], chapters: JSON.parse(fs.readFileSync(path.join(OUT, 'session-1', 'chapters.json'), 'utf8')).chapters },
    { session: 2, duration: durations[1], chapters: JSON.parse(fs.readFileSync(path.join(OUT, 'session-2', 'chapters.json'), 'utf8')).chapters },
  ]);
  const cfg = s[1].config;
  fs.writeFileSync(path.join(OUT, 'chapters.json'), JSON.stringify({
    recorded: new Date().toISOString(), mode: MODE, lang: 'en', stage: STAGE_ON, video: STAGE_ON ? `${ID}.webm` : null,
    duration: merged.duration, durationFrom: STAGE_ON ? 'ffprobe (each session file)' : 'wall-clock',
    sessions: s.map((x) => ({ session: x.session, query: x.query, duration: x.session === 1 ? durations[0] : durations[1] })),
    chapters: merged.chapters,
  }, null, 2));
  fs.writeFileSync(path.join(OUT, 'youtube.md'), renderYoutube({ chapters: merged.chapters, recap: s[1].recap, chat: s[0].chat,
    model: cfg.model, rateDate: cfg.rate_date, thbPerUsd: cfg.thb_per_usd }));
  for (const f of fs.readdirSync(OUT).filter((f) => /\.(webm|mov|json|md)$/.test(f) && f !== 'ledger.md' && f !== 'storyboard.md')) {
    files.push({ name: f, bytes: fs.statSync(path.join(OUT, f)).size });
  }
  fs.writeFileSync(path.join(OUT, 'ledger.md'), renderLedger({
    mode: MODE === 'record' ? `the recording, ${ID}` : `${MODE} of ${ID} (the speed test at ${RUN_SIZE}, not 1,000)`,
    recorded: new Date().toISOString(), chapters: merged.chapters, duration: merged.duration,
    sessions: s.map((x, i) => ({ ...x, duration: durations[i] })), recap: s[1].recap, chat: s[0].chat,
    model: cfg.model, route: '/api/v1/systemone', rateDate: cfg.rate_date, thbPerUsd: cfg.thb_per_usd,
    rateSource: process.env.DEMO_RATE_SOURCE || "THB_PER_USD and RATE_DATE in the owner's .env, served by /api/config",
    assertions, files,
  }));
  console.log(`[demo] assembled ${path.relative(REPO, OUT)}: ${files.map((f) => `${f.name} ${f.bytes} B`).join(', ')}, ledger.md`);
  const bad = assertions.filter((a: any) => !a.ok);
  if (bad.length) { console.error(`[demo] ${bad.length} failed assertion(s) — see ledger.md`); process.exitCode = 4; }
}

// ---------------------------------------------------------------- main

fs.mkdirSync(OUT, { recursive: true });
if (flag('--assemble')) {
  assemble();
} else {
  const which = SESSIONS === 'both' ? [1, 2] : [Number(SESSIONS)];
  let ok = true;
  for (const n of which) {
    const r = await runSession(n as 1 | 2);
    if (!r) { ok = false; break; }
  }
  if (ok && which.includes(2) && fs.existsSync(path.join(OUT, 'session-1', 'session.json'))) assemble();
}
