#!/usr/bin/env node
/**
 * Perceived-speed measurements for a running build, meant to be run against
 * two builds (before/after) on the same backend:
 *
 *   node tests/perf.mjs http://localhost:4173 [runs] > perf-new.json
 *
 * Measures, each as the median of `runs` (default 3) fresh browser contexts:
 *  - cold load of the Photos timeline: first tile in the DOM, first photo
 *    painted, all photos in the first viewport painted; bytes by type
 *  - the same on a reload in the same browser (warm HTTP cache and storage),
 *    which is what reopening the app on a phone looks like
 *  - client-side route switches from the sidebar, first visit and revisit
 *  - viewer open (click to photo on screen) and next/previous step latency
 *  - scrolling the timeline: frame times and long tasks, also at 4x CPU
 *    throttling as a stand-in for a phone
 *
 * Read-only: it navigates, clicks tiles and presses arrow keys.
 * PERF_ONLY=<regex> runs only the matching scenarios (e.g. "scroll").
 */
import { chromium } from "@playwright/test";

const base = (process.argv[2] || "http://localhost:3000").replace(/\/$/, "");
const runs = Number(process.argv[3] || 3);
const search = process.env.PERF_SEARCH || "beach";

const median = (xs) => {
  const s = xs.filter((x) => typeof x === "number" && !Number.isNaN(x)).sort((a, b) => a - b);
  return s.length ? s[Math.floor(s.length / 2)] : null;
};

async function newPage(browser, { cpu = 1, viewport = { width: 1440, height: 900 } } = {}) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  if (cpu > 1) {
    const cdp = await ctx.newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: cpu });
  }
  return { ctx, page };
}

/** Collect transferred bytes per resource type while `fn` runs. */
async function withBytes(page, fn) {
  const totals = {};
  const counts = {};
  const pending = [];
  const onDone = (req) =>
    pending.push(
      req
        .sizes()
        .then((s) => {
          const u = new URL(req.url());
          const type = u.pathname.includes("/thumbnail/")
            ? "thumbnail"
            : u.pathname.startsWith("/api/")
              ? "api"
              : req.resourceType() === "script"
                ? "js"
                : req.resourceType() === "stylesheet"
                  ? "css"
                  : u.hostname.includes("openstreetmap")
                    ? "map-tiles"
                    : "other";
          totals[type] = (totals[type] || 0) + s.responseBodySize;
          counts[type] = (counts[type] || 0) + 1;
        })
        .catch(() => {})
    );
  page.on("requestfinished", onDone);
  const result = await fn();
  await Promise.all(pending);
  page.off("requestfinished", onDone);
  return { result, bytes: totals, counts };
}

/** Page-time (ms since navigation start) at which `predicate` first holds. */
const timeWhen = (page, predicate, arg) =>
  page
    .waitForFunction(
      ([src, a]) => {
        const ok = new Function("a", `return (${src})(a)`)(a);
        return ok ? performance.now() : false;
      },
      [predicate.toString(), arg],
      { polling: "raf", timeout: 60000 }
    )
    .then((h) => h.jsonValue())
    .catch(() => null);

const firstTile = () => !!document.querySelector(".photo-grid-item");
const firstPainted = () =>
  [...document.querySelectorAll(".photo-grid-item img")].some((i) => i.complete && i.naturalWidth > 0);
const viewportPainted = () => {
  const imgs = [...document.querySelectorAll(".photo-grid-item img")].filter((i) => {
    const r = i.getBoundingClientRect();
    return r.bottom > 0 && r.top < innerHeight && r.width > 0;
  });
  return imgs.length > 0 && imgs.every((i) => i.complete && i.naturalWidth > 0);
};

async function coldHome(browser, cpu) {
  const { ctx, page } = await newPage(browser, { cpu });
  const { result, bytes, counts } = await withBytes(page, async () => {
    await page.goto(`${base}/`, { waitUntil: "commit" });
    const tile = await timeWhen(page, firstTile);
    const painted = await timeWhen(page, firstPainted);
    const filled = await timeWhen(page, viewportPainted);
    await page.waitForLoadState("networkidle").catch(() => {});
    return { firstTileMs: tile, firstPhotoMs: painted, viewportFilledMs: filled };
  });
  await ctx.close();
  return { ...result, bytes, counts };
}

async function warmReload(browser) {
  const { ctx, page } = await newPage(browser);
  await page.goto(`${base}/`, { waitUntil: "domcontentloaded" });
  await timeWhen(page, viewportPainted);
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(1500); // let anything that persists data finish
  await page.goto(`${base}/`, { waitUntil: "commit" });
  const tile = await timeWhen(page, firstTile);
  const filled = await timeWhen(page, viewportPainted);
  await ctx.close();
  return { firstTileMs: tile, viewportFilledMs: filled };
}

/** Ready: no spinner in main, and something rendered in it. */
const pageReady = () =>
  !document.querySelector("main .animate-spin") &&
  !!document.querySelector("main h1, main h2, main .photo-grid-item, main .leaflet-container, main table");

async function routeSwitches(browser) {
  const { ctx, page } = await newPage(browser);
  await page.goto(`${base}/`, { waitUntil: "domcontentloaded" });
  await timeWhen(page, viewportPainted);
  const labels = ["Favorites", "People", "Events", "Tags", "Years", "Videos", "Locations", "Pipeline", "Photos"];
  const out = {};
  for (const pass of ["first", "revisit"]) {
    for (const label of labels) {
      const link = page.locator(`aside >> text="${label}"`).first();
      const t0 = await page.evaluate(() => performance.now());
      await link.click();
      const t1 = await timeWhen(page, pageReady);
      out[`${pass}:${label}`] = t1 === null ? null : Math.round(t1 - t0);
      await page.waitForLoadState("networkidle").catch(() => {});
    }
  }
  await ctx.close();
  return out;
}

async function viewer(browser) {
  const { ctx, page } = await newPage(browser);
  await page.goto(`${base}/search?q=${encodeURIComponent(search)}`, { waitUntil: "domcontentloaded" });
  await timeWhen(page, viewportPainted);
  await page.waitForLoadState("networkidle").catch(() => {});

  const open = await page.evaluate(
    () =>
      new Promise((resolve) => {
        const tile = document.querySelector(".photo-grid-item");
        const t0 = performance.now();
        tile.click();
        let shown = null;
        const tick = () => {
          const img = document.querySelector('img[data-testid="full-view"]');
          if (img && shown === null) shown = performance.now() - t0;
          if (img && img.complete && img.naturalWidth > 0) {
            resolve({ shownMs: shown, decodedMs: performance.now() - t0 });
            return;
          }
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      })
  );

  const step = (key) =>
    page.evaluate(
      (k) =>
        new Promise((resolve) => {
          const before = document.querySelector('img[data-testid="full-view"]')?.getAttribute("src");
          const t0 = performance.now();
          document.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));
          let swapped = null;
          const tick = () => {
            const img = document.querySelector('img[data-testid="full-view"]');
            const src = img?.getAttribute("src");
            if (src && src !== before && swapped === null) swapped = performance.now() - t0;
            if (swapped !== null && img.complete && img.naturalWidth > 0) {
              resolve({ swapMs: swapped, decodedMs: performance.now() - t0 });
              return;
            }
            if (performance.now() - t0 > 30000) return resolve({ swapMs: swapped, decodedMs: null });
            requestAnimationFrame(tick);
          };
          requestAnimationFrame(tick);
        }),
      key
    );

  const steps = [];
  for (const key of ["ArrowRight", "ArrowRight", "ArrowRight", "ArrowLeft", "ArrowLeft"]) {
    await page.waitForTimeout(400); // let the prefetch of neighbours happen, as a person would
    steps.push(await step(key));
  }
  await ctx.close();
  return {
    openShownMs: open.shownMs,
    openDecodedMs: open.decodedMs,
    stepSwapMs: median(steps.map((s) => s.swapMs)),
    stepDecodedMs: median(steps.map((s) => s.decodedMs)),
  };
}

async function scroll(browser, cpu) {
  const { ctx, page } = await newPage(browser, { cpu });
  await page.goto(`${base}/`, { waitUntil: "domcontentloaded" });
  await timeWhen(page, viewportPainted);
  await page.waitForLoadState("networkidle").catch(() => {});
  const r = await page.evaluate(
    () =>
      new Promise((resolve) => {
        const scroller = document.querySelector("main .overflow-y-auto");
        const longTasks = [];
        const obs = new PerformanceObserver((list) => {
          for (const e of list.getEntries()) longTasks.push(e.duration);
        });
        obs.observe({ type: "longtask", buffered: false });
        const frames = [];
        let last = performance.now();
        const end = last + 6000;
        const tick = (now) => {
          frames.push(now - last);
          last = now;
          scroller.scrollTop += 60; // ~3600 px/s at 60fps, a brisk flick
          if (now < end) requestAnimationFrame(tick);
          else {
            obs.disconnect();
            frames.sort((a, b) => a - b);
            resolve({
              frames: frames.length,
              p95FrameMs: Math.round(frames[Math.floor(frames.length * 0.95)]),
              slowFrames: frames.filter((f) => f > 50).length,
              longTasks: longTasks.length,
              longTaskMs: Math.round(longTasks.reduce((a, b) => a + b, 0)),
              scrolledPx: scroller.scrollTop,
            });
          }
        };
        requestAnimationFrame(tick);
      })
  );
  await ctx.close();
  return r;
}

const browser = await chromium.launch();
const results = { base, runs };
const only = process.env.PERF_ONLY ? new RegExp(process.env.PERF_ONLY) : null;
const collect = async (name, fn) => {
  if (only && !only.test(name)) return;
  const all = [];
  for (let i = 0; i < runs; i++) all.push(await fn());
  const keys = Object.keys(all[0]).filter((k) => typeof all[0][k] === "number" || all[0][k] === null);
  const med = Object.fromEntries(keys.map((k) => [k, median(all.map((a) => a[k]))]));
  if (all[0].bytes) {
    med.bytes = Object.fromEntries(Object.keys(all[0].bytes).map((k) => [k, median(all.map((a) => a.bytes[k]))]));
    med.counts = Object.fromEntries(Object.keys(all[0].counts).map((k) => [k, median(all.map((a) => a.counts[k]))]));
  }
  if (name === "routes") {
    for (const k of Object.keys(all[0])) med[k] = median(all.map((a) => a[k]));
  }
  results[name] = med;
  console.error(name, JSON.stringify(med));
};

await collect("coldHome", () => coldHome(browser, 1));
await collect("coldHomeCpu4x", () => coldHome(browser, 4));
await collect("warmReload", () => warmReload(browser));
await collect("routes", () => routeSwitches(browser));
await collect("viewer", () => viewer(browser));
await collect("scroll", () => scroll(browser, 1));
await collect("scrollCpu4x", () => scroll(browser, 4));
await browser.close();
console.log(JSON.stringify(results, null, 2));
