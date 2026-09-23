/**
 * demo_stage.ts — the stage for a client cut (Loop 2e, `/npch:orb2e-client-demo`).
 *
 * Copy to tests/demo/stage.ts. Three layers over the product — a chapter card, a pointing
 * callout, a subtitle line — plus a visible cursor and a human's pace, all injected as DOM into
 * the page Playwright is already recording. No compositor, no post-production, no second track.
 *
 * Set DEMO_STAGE=0 for the rehearsal: every overlay and every human delay off, the same script,
 * a minute instead of ten. It proves the path. It does not prove the pace.
 *
 * Sizes are the deliverable, not a suggestion — see references/stage.md. The one number worth
 * remembering: the caption this replaces was 18 px on a 1080p frame, 1.7 % of frame height,
 * readable by the person who wrote the product and nobody else.
 *
 * Local changes to the plugin's copy (Scripted-Chatbot-with-Jev, Story 2.5), each marked `[local]`:
 * - `StageOptions.subtitleFloor` / `subtitlePadY`: the page reserves a 72 px bottom band for the
 *   subtitle (storyboard § 4) so the composer and the key-info block are never covered; the band
 *   sits inside the 54 px bottom safe area, so the safe-area check lets the subtitle reach it.
 * - `chapter(…, { legible: false })`: the owner ruled 16 px labels acceptable on the sparse opening
 *   frames (F-20); the font floor is skipped there, the safe-area check still runs.
 * - `stage.legible()`: the full check on demand, at a dense frame the driver chooses, returning the
 *   measure so the ledger can quote it.
 * - `callout(…, { holdMs })`: a longer hold than the reading-speed floor, for the storyboard's pace.
 * - `callout(…, { beside })`: the bubble sits outside a container (a panel row, the key-info block)
 *   on the chosen side, and the arrow's dot lands on that container's edge level with the anchor —
 *   so neither the bubble nor the dot covers a figure of the thing it points at.
 */
import { expect, type BrowserContext, type Locator, type Page } from '@playwright/test';
import { execFileSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

export const STAGE_ON = process.env.DEMO_STAGE !== '0';

/** Every size in one place, so a change is one edit and assertLegible reads the same numbers. */
export const SIZE = {
  cardTitle: 76, cardNumber: 40, cardIdea: 32, cardHoldMs: 2200, cardFadeMs: 240,
  chip: 24, callout: 30, calloutLineMax: 44, calloutLines: 2, calloutHoldMinMs: 2500,
  readCharsPerSec: 13,
  subtitle: 34, subtitleCharsMax: 66, subtitleFloor: 72,
  badge: 24,
  safeX: 96, safeY: 54,
  minBodyPx: 20,
} as const;

type Lang = 'en' | 'th';
type Drive = 'built' | 'prototype';

export interface StageOptions {
  lang?: Lang;
  /** demos/<audience>-<YYYY-MM-DD> — where chapters.json, posters/ and the video land. */
  demoDir: string;
  /** How many chapters the storyboard has, for the "2 of 6" chip. */
  chapters: number;
  /** [local] px from the frame's floor to the subtitle's bottom edge (default SIZE.subtitleFloor). */
  subtitleFloor?: number;
  /** [local] the subtitle's vertical padding in px (default 16). */
  subtitlePadY?: number;
}

export interface ChapterStamp {
  n: number; title: string; idea: string; drive: Drive;
  /** Seconds from the video's first frame. */
  t: number;
  /** The same instant as `m:ss`, written here so the deck and the script never compute it. */
  mmss: string;
  /** Seconds until the next chapter, or to the end — what the narration has to fit inside. */
  seconds: number;
  poster: string | null;
}

// Single quotes, deliberately: the chapter card injects this inside a double-quoted style="..."
// attribute, and a double quote in the family name closes the attribute early. The font shorthand
// then parses as invalid, the whole declaration is dropped, and a 76 px title silently renders at
// the page's default size. It looked like a zoom bug for ten minutes.
const FONT = (lang: Lang) => lang === 'th'
  ? `'Noto Sans Thai', Sarabun, system-ui, -apple-system, sans-serif`
  : `-apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, system-ui, sans-serif`;

/** State the overlays need again after a navigation blows the DOM away. */
interface Persist { chip: string | null; badge: boolean; subtitle: string | null; zoom: number }

export async function openStage(page: Page, opts: StageOptions) {
  const lang: Lang = opts.lang ?? 'en';
  const demoDir = opts.demoDir;
  const posterDir = path.join(demoDir, 'posters');
  const subFloor = opts.subtitleFloor ?? SIZE.subtitleFloor;   // [local]
  const subPadY = opts.subtitlePadY ?? 16;                     // [local]
  fs.mkdirSync(posterDir, { recursive: true });

  const stamps: ChapterStamp[] = [];
  const persist: Persist = { chip: null, badge: false, subtitle: null, zoom: 1 };
  let mouse = { x: 12, y: 12 };
  let current = 0;
  // The clock starts HERE, not at the first chapter: Playwright began recording when the context
  // was created, and a chapter stamped from the first chapter() call is offset by however long the
  // first navigation took. Call openStage as the first line of the test. A three-chapter smoke cut
  // stamped its last chapter at 13.02 s of a 24.3 s video before this line existed.
  const t0 = Date.now();

  // The cursor and the overlay root are installed here, once, or they vanish on the first
  // navigation. addInitScript runs again on every document.
  if (STAGE_ON) {
    await page.addInitScript(() => {
      const mount = () => {
        if (!document.body || document.getElementById('stage-root')) return;
        const root = document.createElement('div');
        root.id = 'stage-root';
        root.style.cssText =
          'position:fixed;inset:0;z-index:2147483000;pointer-events:none;contain:layout style';
        // On <html>, NOT on body: the stage zoom is applied to body, and an overlay inside a
        // zoomed element has its coordinates scaled with it — while the anchor rectangles come
        // from Playwright unzoomed. At zoom 1.9 that put every callout off the right edge of the
        // frame and made the spotlight invisible.
        document.documentElement.appendChild(root);

        const cur = document.createElement('div');
        cur.id = 'stage-cursor';
        cur.style.cssText =
          'position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483100;' +
          'pointer-events:none;transform:translate(-2px,-2px);transition:transform .08s';
        cur.innerHTML =
          '<svg width="26" height="26" viewBox="0 0 22 22"><path d="M2 2 L2 18 L6.5 14 ' +
          'L9.5 20.5 L12.5 19 L9.5 12.5 L15.5 12.5 Z" fill="#111827" stroke="#fff" ' +
          'stroke-width="1.6" stroke-linejoin="round"/></svg>';
        document.documentElement.appendChild(cur);
        addEventListener('mousemove', (e: MouseEvent) => {
          cur.style.left = e.clientX + 'px'; cur.style.top = e.clientY + 'px';
        }, true);
        addEventListener('mousedown', () => {
          cur.style.transform = 'translate(-2px,-2px) scale(.82)';
        }, true);
        addEventListener('mouseup', () => {
          cur.style.transform = 'translate(-2px,-2px)';
        }, true);
      };
      if (document.body) mount();
      else document.addEventListener('DOMContentLoaded', mount);
    });
  }

  const ms = (n: number) => (STAGE_ON ? page.waitForTimeout(n) : Promise.resolve());

  /**
   * The in-frame layers scale with the stage zoom. They are mounted outside the zoomed element, so
   * without this a chapter at zoom 1.9 shows a product at ~30 px effective text under a 34 px
   * subtitle — the label stops being the loudest thing in frame, which is the whole job of a
   * label. The chapter card does not scale: it is full bleed and competes with nothing.
   */
  const ui = () => Math.max(1, persist.zoom);

  /** Put the persistent layers back after a navigation. */
  async function reapply() {
    if (!STAGE_ON) return;
    await page.evaluate(({ p, S, font, k, floor, padY }) => {
      const root = document.getElementById('stage-root');
      if (!root) return;
      document.body.style.zoom = String(p.zoom);
      const put = (id: string, css: string, html: string) => {
        let el = document.getElementById(id);
        if (!el) { el = document.createElement('div'); el.id = id; root.appendChild(el); }
        el.style.cssText = css; el.innerHTML = html;
      };
      const gone = (id: string) => document.getElementById(id)?.remove();

      if (p.chip) {
        put('stage-chip',
          `position:fixed;left:${S.safeX}px;top:${S.safeY}px;` +
          `font:600 ${S.chip * k}px/1.2 ${font};` +
          'color:#fff;background:rgba(17,24,39,.86);padding:10px 16px;border-radius:999px;' +
          'letter-spacing:.01em', p.chip);
      } else gone('stage-chip');

      if (p.badge) {
        put('stage-badge',
          `position:fixed;right:${S.safeX}px;top:${S.safeY}px;` +
          `font:700 ${S.badge * k}px/1.2 ${font};` +
          'color:#7c2d12;background:#fbbf24;padding:10px 16px;border-radius:6px;' +
          'letter-spacing:.10em', 'DESIGN PREVIEW');
      } else gone('stage-badge');

      if (p.subtitle) {
        put('stage-subtitle',
          `position:fixed;left:${S.safeX}px;right:${S.safeX}px;bottom:${floor}px;` +
          `font:500 ${S.subtitle * k}px/1.3 ${font};color:#fff;background:rgba(10,13,18,.92);` +
          `padding:${padY}px 24px;border-radius:10px;text-align:center`, p.subtitle);
      } else gone('stage-subtitle');
    }, { p: persist, S: SIZE, font: FONT(lang), k: ui(), floor: subFloor, padY: subPadY }).catch(() => {});
  }
  page.on('load', () => { void reapply().catch(() => {}); });

  /**
   * Refuse the run rather than produce an unreadable video. Called by chapter().
   * A failure names the measured value: raise the stage zoom, or the storyboard is asking for a
   * screen too dense to demo.
   */
  async function assertLegible(floor = true) {
    if (!STAGE_ON) return null;
    const vp = page.viewportSize();
    expect(vp, 'the stage needs a fixed viewport').not.toBeNull();
    const m = await page.evaluate(({ S, subFloor }) => {
      const sizes: number[] = [];
      const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = walk.nextNode(); n; n = walk.nextNode()) {
        const t = (n.textContent || '').trim();
        if (t.length < 3) continue;
        const el = n.parentElement;
        if (!el || el.closest('#stage-root')) continue;
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        sizes.push(parseFloat(cs.fontSize));
      }
      sizes.sort((a, b) => a - b);
      const zoom = parseFloat(document.body.style.zoom || '1') || 1;
      // The 10th percentile, not the minimum: one stray 9 px legal line is not the demo.
      const p10 = sizes.length ? sizes[Math.floor(sizes.length * 0.1)] : NaN;
      const over = Array.from(document.querySelectorAll('#stage-root > *')).map((e) => {
        const r = e.getBoundingClientRect();
        // [local] the subtitle may sit lower than the safe area when the page reserves a band for it
        const floorY = e.id === 'stage-subtitle' ? Math.min(S.safeY, subFloor) : S.safeY;
        return (r.left < S.safeX - 1 || r.right > innerWidth - S.safeX + 1 ||
                r.top < S.safeY - 1 || r.bottom > innerHeight - floorY + 1) ? e.id : null;
      }).filter(Boolean);
      return { p10, zoom, n: sizes.length, over };
    }, { S: SIZE, subFloor });

    if (floor && !Number.isNaN(m.p10)) {   // [local] skipped on the sparse opening frames (F-20)
      expect(m.p10 * m.zoom,
        `the page's body text measures ${(m.p10 * m.zoom).toFixed(1)} px at zoom ${m.zoom} — ` +
        `under ${SIZE.minBodyPx} px it is not readable in a video watched at half size. ` +
        'Raise the stage zoom, or this screen is too dense to demo.')
        .toBeGreaterThanOrEqual(SIZE.minBodyPx);
    }
    expect(m.over,
      'an overlay crosses the safe area, where a player\'s controls live').toEqual([]);
    return m;
  }

  const stage = {
    stamps,

    /**
     * The card, the chip, the badge, and the chapter's t. Clears the subtitle and sets this
     * chapter's zoom — pass it here, not after, because the legibility assertion runs at the end
     * of this call and a zoom applied afterwards is a zoom the assertion never saw.
     */
    async chapter(n: number, title: string, idea: string,
                  o: { drive?: Drive; zoom?: number; legible?: boolean } = {}) {
      const drive: Drive = o.drive ?? 'built';
      const t = (Date.now() - t0) / 1000;
      current = n;
      stamps.push({ n, title, idea, drive, t: Number(t.toFixed(2)),
                    mmss: '', seconds: 0, poster: null });

      persist.zoom = o.zoom ?? 1;
      persist.subtitle = null;
      persist.chip = `${n} of ${opts.chapters} · ${title}`;
      persist.badge = drive === 'prototype';

      if (STAGE_ON) {
        await page.evaluate(({ n, title, idea, S, font }) => {
          const root = document.getElementById('stage-root');
          if (!root) return;
          // The card is the same size in every chapter because it is mounted outside the zoomed
          // element. When it was not, the previous chapter's 1.9 rendered chapter 2's title at
          // 144 px and chapter 1's at 76 — a title card that changes size looks broken.
          const cur = document.getElementById('stage-cursor');
          if (cur) cur.style.display = 'none';
          const card = document.createElement('div');
          card.id = 'stage-card';
          card.style.cssText =
            'position:fixed;inset:0;background:#0b0f16;color:#fff;display:flex;' +
            'flex-direction:column;justify-content:center;align-items:flex-start;' +
            `padding:0 ${S.safeX * 1.6}px;opacity:0;transition:opacity ${S.cardFadeMs}ms`;
          card.innerHTML =
            `<div style="font:600 ${S.cardNumber}px/1 ${font};color:#fbbf24;` +
            `margin-bottom:20px">${n}</div>` +
            `<div style="font:700 ${S.cardTitle}px/1.1 ${font};letter-spacing:-.01em">` +
            `${title}</div>` +
            `<div style="width:180px;height:3px;background:#fbbf24;margin:28px 0"></div>` +
            `<div style="font:400 ${S.cardIdea}px/1.4 ${font};color:#cbd5e1;max-width:22em">` +
            `${idea}</div>`;
          root.appendChild(card);
          requestAnimationFrame(() => { card.style.opacity = '1'; });
        }, { n, title, idea, S: SIZE, font: FONT(lang) }).catch(() => {});
        await ms(SIZE.cardHoldMs);
        await page.evaluate(({ fade }) => {
          const cur = document.getElementById('stage-cursor');
          if (cur) cur.style.display = '';
          const c = document.getElementById('stage-card');
          if (!c) return;
          c.style.opacity = '0';
          setTimeout(() => c.remove(), fade + 40);
        }, { fade: SIZE.cardFadeMs }).catch(() => {});
        await ms(SIZE.cardFadeMs + 60);
      }
      await reapply();
      await assertLegible(o.legible !== false);
    },

    /** [local] The full legibility check at a frame the driver chooses; returns the measure. */
    legible: () => assertLegible(true),

    /** Change the zoom inside a chapter — reset by the next chapter(). Re-asserts legibility. */
    async zoom(factor: number) {
      persist.zoom = factor;
      if (!STAGE_ON) return;
      await page.evaluate((z) => { document.body.style.zoom = String(z); }, factor)
        .catch(() => {});
      await ms(300);
      await assertLegible();
    },

    async subtitle(text: string | null) {
      persist.subtitle = text;
      if (text && text.length > SIZE.subtitleCharsMax) {
        throw new Error(
          `subtitle is ${text.length} characters, over ${SIZE.subtitleCharsMax}: "${text}". ` +
          'Shorten it in the storyboard, not here — the storyboard is what was approved.');
      }
      await reapply();
      await ms(400);
    },

    /**
     * One idea, pointed at one thing. Two callouts on screen at once is a frame nobody reads,
     * so this shows, holds and clears.
     */
    async callout(anchor: string | Locator, text: string,
                  o: { spotlight?: boolean; side?: 'right' | 'left' | 'top' | 'bottom';
                       poster?: boolean; holdMs?: number; beside?: string } = {}) {
      const loc = typeof anchor === 'string' ? page.locator(anchor).first() : anchor;
      await loc.scrollIntoViewIfNeeded().catch(() => {});
      const box = await loc.boundingBox();
      if (!box) throw new Error(`callout anchor is not on screen: ${String(anchor)}`);
      // [local] beside: the container the bubble and the dot stay outside of.
      const outer = o.beside ? await page.locator(o.beside).first().boundingBox() : null;
      if (o.beside && !outer) throw new Error(`callout container is not on screen: ${o.beside}`);
      if (!STAGE_ON) return;

      await page.evaluate(({ box, outer, text, side, spot, S, font, k }) => {
        const root = document.getElementById('stage-root');
        if (!root) return;
        const wrap = document.createElement('div');
        wrap.id = 'stage-callout';
        root.appendChild(wrap);

        if (spot) {
          const sp = document.createElement('div');
          sp.style.cssText =
            `position:fixed;left:${box.x - 6}px;top:${box.y - 6}px;` +
            `width:${box.width + 12}px;height:${box.height + 12}px;border-radius:8px;` +
            'box-shadow:0 0 0 9999px rgba(12,16,24,.55);outline:3px solid #fbbf24';
          wrap.appendChild(sp);
        }

        const bub = document.createElement('div');
        bub.style.cssText =
          `position:fixed;font:600 ${S.callout * k}px/1.35 ${font};color:#0b0f16;background:#fff;` +
          `padding:${16 * k}px ${20 * k}px;border-radius:12px;max-width:${S.calloutLineMax}ch;` +
          'box-shadow:0 10px 40px rgba(0,0,0,.35);transform:scale(.9);opacity:0;' +
          'transition:transform .18s cubic-bezier(.2,.9,.3,1.2),opacity .18s';
        bub.textContent = text;
        wrap.appendChild(bub);

        const gap = 44;
        // [local] The layout size, not the drawn one: the bubble enters at scale(.9), so its drawn
        // box is 10 % small and at full size it grew over the thing it was placed beside.
        const r = { width: bub.offsetWidth, height: bub.offsetHeight };
        // [local] Placed against the container when one is given, level with the anchor.
        const c = outer || box;
        let x = c.x + c.width + gap, y = box.y + box.height / 2 - r.height / 2;
        if (side === 'left') x = c.x - gap - r.width;
        if (side === 'top') { x = box.x + box.width / 2 - r.width / 2; y = c.y - gap - r.height; }
        if (side === 'bottom') { x = box.x + box.width / 2 - r.width / 2; y = c.y + c.height + gap; }
        x = Math.max(S.safeX, Math.min(x, innerWidth - S.safeX - r.width));
        y = Math.max(S.safeY, Math.min(y, innerHeight - S.safeY - r.height));

        // The chip, the badge and the subtitle own their bands. A callout landing on one covers
        // the very thing that says where the viewer is, or that this screen is not built yet.
        const reserved = ['stage-chip', 'stage-badge', 'stage-subtitle']
          .map((id) => document.getElementById(id))
          .filter(Boolean)
          .map((e) => (e as HTMLElement).getBoundingClientRect());
        const hits = (top: number) => reserved.some((q) =>
          !(x + r.width < q.left || x > q.right || top + r.height < q.top || top > q.bottom));
        if (hits(y)) {
          const tops = reserved.filter((q) => q.top < innerHeight / 2).map((q) => q.bottom);
          const bots = reserved.filter((q) => q.top >= innerHeight / 2).map((q) => q.top);
          const down = (tops.length ? Math.max(...tops) : S.safeY) + 20;
          const up = (bots.length ? Math.min(...bots) : innerHeight - S.safeY) - 20 - r.height;
          const cand = [down, up].filter((v) => v >= S.safeY &&
                                                v + r.height <= innerHeight - S.safeY && !hits(v));
          if (cand.length) {
            cand.sort((a, b) => Math.abs(a - y) - Math.abs(b - y));
            y = cand[0];
          }
        }
        bub.style.left = x + 'px'; bub.style.top = y + 'px';

        // The arrow: from the bubble's nearest edge to the nearest point of the anchor.
        const bx = x + r.width / 2, by = y + r.height / 2;
        let ax = Math.max(box.x, Math.min(bx, box.x + box.width));
        let ay = Math.max(box.y, Math.min(by, box.y + box.height));
        if (outer) {   // [local] the dot on the container's edge, level with the anchor's middle
          const mx = box.x + box.width / 2, my = box.y + box.height / 2;
          if (side === 'left') { ax = outer.x - 8; ay = my; }
          if (side === 'right') { ax = outer.x + outer.width + 8; ay = my; }
          if (side === 'top') { ax = mx; ay = outer.y - 4; }
          if (side === 'bottom') { ax = mx; ay = outer.y + outer.height + 4; }
        }
        const ux = (ax - bx), uy = (ay - by), len = Math.hypot(ux, uy) || 1;
        const sx = bx + (ux / len) * Math.min(r.width / 2 + 4, len);
        const sy = by + (uy / len) * Math.min(r.height / 2 + 4, len);
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('style', 'position:fixed;inset:0;width:100%;height:100%;overflow:visible');
        svg.innerHTML =
          `<line x1="${sx}" y1="${sy}" x2="${ax}" y2="${ay}" stroke="#fbbf24" stroke-width="3"` +
          ` stroke-linecap="round"/><circle cx="${ax}" cy="${ay}" r="7" fill="#fbbf24"/>`;
        wrap.insertBefore(svg, bub);

        requestAnimationFrame(() => { bub.style.transform = 'scale(1)'; bub.style.opacity = '1'; });
      }, { box, outer, text, side: o.side ?? 'right', spot: !!o.spotlight, S: SIZE, font: FONT(lang),
           k: ui() })
        .catch(() => {});

      await ms(Math.max(SIZE.calloutHoldMinMs, o.holdMs ?? 0,   // [local] holdMs
                        (text.length / SIZE.readCharsPerSec) * 1000));
      // The still is taken WITH the callout up: a poster in the deck without the thing that
      // explains it is a screenshot of a screen the reader has never seen.
      if (o.poster) await stage.poster();
      await page.evaluate(() => document.getElementById('stage-callout')?.remove())
        .catch(() => {});
      await ms(200);
    },

    /** The eye's pause, not the page's. A no-op in the rehearsal. */
    pause: (n: number) => ms(n),

    /** A settle with a floor, so a fast page still gives the viewer a beat. */
    settle: (n = 700) => page.waitForTimeout(STAGE_ON ? Math.max(n, 900) : n),

    async humanClick(target: Locator, o: { hover?: number; after?: number } = {}) {
      const el = target.first();
      await el.scrollIntoViewIfNeeded().catch(() => {});
      if (!STAGE_ON) { await el.click(); return; }
      const box = await el.boundingBox();
      if (!box) { await el.click(); return; }
      const x = box.x + Math.min(box.width / 2, 180), y = box.y + box.height / 2;
      await page.mouse.move(mouse.x, mouse.y);
      await page.mouse.move(x, y, { steps: 14 });   // it moves, it does not teleport
      mouse = { x, y };
      await page.waitForTimeout(o.hover ?? 260);
      await page.mouse.down();
      await page.waitForTimeout(70);                 // a press has to be visible
      await page.mouse.up();
      await page.waitForTimeout(o.after ?? 900);
    },

    async humanType(target: Locator, value: string,
                    o: { delay?: number; clear?: boolean } = {}) {
      const el = target.first();
      if (!STAGE_ON) { await el.fill(value); return; }
      await stage.humanClick(el, { after: 250 });
      if (o.clear !== false) await el.fill('');
      await el.pressSequentially(value, { delay: o.delay ?? 55 });
      await page.waitForTimeout(500);
    },

    /** One still per chapter, for the deck. Viewport only — it must match what the video shows. */
    async poster() {
      const n = String(current).padStart(2, '0');
      const file = path.join(posterDir, `${n}.png`);
      await page.screenshot({ path: file, fullPage: false });
      const s = stamps.find((c) => c.n === current);
      if (s) s.poster = path.relative(demoDir, file);
      return file;
    },

    /**
     * Write chapters.json, then close the context, THEN save the video — in that order.
     * Saving before the close yields a truncated file, and the video is the one artifact that
     * cannot be reproduced without paying for the pass again.
     */
    async close(context: BrowserContext, videoName: string) {
      if (STAGE_ON) await ms(2500);                  // do not cut on the last click
      const wall = (Date.now() - t0) / 1000;
      const video = page.video();
      await context.close();
      let dest: string | null = null;
      let bytes = 0;
      if (video) {
        dest = path.join(demoDir, videoName);
        await video.saveAs(dest);
        bytes = fs.statSync(dest).size;
      }

      // The duration comes off the FILE, never off the clock. The recorder pads the tail, and a
      // wall-clock figure was 21.67 s over a 23.64 s video — the same two-numbers-for-one-fact
      // defect as a ledger header reading "9 min" over a 9 min 24 s recording.
      let duration = Number(wall.toFixed(2));
      let measured = false;
      if (dest) {
        try {
          const out = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration',
                                               '-of', 'csv=p=0', dest], { encoding: 'utf8' });
          const d = parseFloat(out.trim());
          if (Number.isFinite(d) && d > 0) { duration = Number(d.toFixed(2)); measured = true; }
        } catch {
          console.warn('[stage] ffprobe not available — duration is wall-clock, not the file\'s');
        }
      }

      stamps.forEach((c, i) => {
        c.seconds = Number(((stamps[i + 1]?.t ?? duration) - c.t).toFixed(2));
        c.mmss = `${Math.floor(c.t / 60)}:${String(Math.floor(c.t % 60)).padStart(2, '0')}`;
      });
      fs.writeFileSync(path.join(demoDir, 'chapters.json'),
        JSON.stringify({ recorded: new Date().toISOString(), lang, stage: STAGE_ON,
                         video: dest ? path.basename(dest) : null,
                         bytes, duration, durationFrom: measured ? 'ffprobe' : 'wall-clock',
                         chapters: stamps }, null, 2));
      if (dest) console.log(`[stage] video → ${dest} (${(bytes / 1e6).toFixed(1)} MB, ${duration}s)`);
      return dest;
    },
  };

  await reapply();
  return stage;
}
