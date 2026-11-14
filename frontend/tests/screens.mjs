#!/usr/bin/env node
/**
 * Screenshot every route at desktop and phone size, and record which API
 * requests each page makes. Run it against two builds and compare the output
 * directories with tests/compare-screens.mjs to see what a change did to the
 * UI and to the API traffic.
 *
 *   node tests/screens.mjs http://localhost:3000 /tmp/shots-new
 *
 * Not a Playwright spec on purpose: it asserts nothing and never mutates data
 * (it only navigates, clicks tiles and presses viewer keys), so it is safe to
 * point at any instance. Route parameters (person, event, tag...) are taken
 * from the instance's own API, the first of each, so two runs against the same
 * data visit the same pages. Override any with SCREENS_PERSON, SCREENS_TOGETHER,
 * SCREENS_EVENT, SCREENS_TAG, SCREENS_COUNTRY, SCREENS_CITY, SCREENS_FOLDER,
 * SCREENS_YEAR, SCREENS_SEARCH; SCREENS_ONLY=<regex> limits the shots taken.
 *
 * SCREENS_CSP="<policy>" serves every page with that Content-Security-Policy
 * and reports each violation as an error, to check a policy before nginx
 * enforces it.
 */
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const base = (process.argv[2] || "http://localhost:3000").replace(/\/$/, "");
const out = process.argv[3] || "screens";
const only = process.env.SCREENS_ONLY ? new RegExp(process.env.SCREENS_ONLY) : null;

async function discover() {
  const get = async (p) => (await fetch(`${base}/api${p}`)).json();
  const persons = await get("/persons?page_size=200");
  const groups = await get("/persons/groups/together?min_photos=3");
  const events = await get("/events?page_size=1");
  const tags = await get("/tags?limit=1");
  const countries = await get("/locations/countries");
  const country = countries[0]?.country;
  const cities = await get(`/locations/cities?country=${encodeURIComponent(country)}`);
  const tree = await get("/directories");
  const folder = tree.find((n) => n.children.length)?.children[0]?.path ?? tree[0]?.path;
  const years = await get("/timeline/years");
  return {
    person: persons[0]?.person_id,
    together: groups[0]?.persons.map((p) => p.person_id).join(","),
    event: events[0]?.event_id,
    tag: tags.items[0]?.tag_id,
    country,
    city: cities[0]?.city,
    folder,
    year: years[0]?.year,
  };
}

const found = await discover();
const env = (name) => process.env[`SCREENS_${name.toUpperCase()}`];
const p = Object.fromEntries(Object.entries(found).map(([k, v]) => [k, env(k) || v]));
const search = env("search") || "beach";
console.log("route parameters:", JSON.stringify({ ...p, search }));
const enc = (s) => String(s).split("/").map(encodeURIComponent).join("/");

const ROUTES = [
  ["home", "/"],
  ["years", "/years"],
  ["year", `/years/${p.year}`],
  ["folders", "/folders"],
  ["folder", `/folders/${enc(p.folder)}`],
  ["people", "/people"],
  ["person", `/people/${p.person}`],
  ["together", `/people/together/${p.together}`],
  ["events", "/events"],
  ["event", `/events/${p.event}`],
  ["locations-list", "/locations?view=countries"],
  ["country", `/locations/${encodeURIComponent(p.country)}`],
  ["city", `/locations/${encodeURIComponent(p.country)}/${encodeURIComponent(p.city)}`],
  ["map", "/locations"],
  ["tags", "/tags"],
  ["tag", `/tags/${p.tag}`],
  ["favorites", "/favorites"],
  ["flagged", "/flagged"],
  ["videos", "/videos"],
  ["to-print", "/to-print"],
  ["large-files", "/large-files"],
  ["duplicates", "/duplicates"],
  ["search", `/search?q=${encodeURIComponent(search)}`],
  ["pipeline", "/pipeline"],
  ["export-import", "/export-import"],
];

const VIEWPORTS = [
  { name: "desktop", viewport: { width: 1440, height: 900 } },
  {
    name: "phone",
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  },
];

/** Settle: network quiet, spinners gone, lazy images in view decoded. */
async function settle(page) {
  await page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => {});
  await page
    .waitForSelector("main .animate-spin", { state: "detached", timeout: 30000 })
    .catch(() => {});
  await page.waitForLoadState("networkidle", { timeout: 30000 }).catch(() => {});
  await page
    .waitForFunction(
      () =>
        [...document.images].every((img) => {
          const r = img.getBoundingClientRect();
          const visible = r.bottom > 0 && r.top < innerHeight && r.width > 0;
          return !visible || img.complete;
        }),
      null,
      { timeout: 20000 }
    )
    .catch(() => {});
  await page.waitForTimeout(400);
}

const browser = await chromium.launch();
const report = {};

for (const vp of VIEWPORTS) {
  const dir = path.join(out, vp.name);
  fs.mkdirSync(dir, { recursive: true });
  const { name: _n, ...ctxOpts } = vp;
  const ctx = await browser.newContext({ ...ctxOpts, deviceScaleFactor: 1, locale: "en-GB", timezoneId: "Europe/Amsterdam" });
  const page = await ctx.newPage();

  let requests = [];
  let errors = [];
  if (process.env.SCREENS_CSP) {
    await page.route(
      (url) => url.origin === new URL(base).origin && !url.pathname.startsWith("/api/") && !/\.\w+$/.test(url.pathname),
      async (route) => {
        const res = await route.fetch();
        await route.fulfill({ response: res, headers: { ...res.headers(), "content-security-policy": process.env.SCREENS_CSP } });
      }
    );
    await page.exposeFunction("__cspViolation", (v) => errors.push(`csp: ${v}`));
    await page.addInitScript(() => {
      document.addEventListener("securitypolicyviolation", (e) =>
        window.__cspViolation(`${e.violatedDirective} blocked ${e.blockedURI || "inline"}`)
      );
    });
  }
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/api/") && !/\/(thumbnail|original|preview|live)/.test(u.pathname)) {
      requests.push(`${r.method()} ${u.pathname}${u.search}`);
    }
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !m.text().includes("WebSocket")) errors.push(`console: ${m.text()}`);
  });

  const shoot = async (name, fn) => {
    if (only && !only.test(name)) return;
    requests = [];
    errors = [];
    const t0 = Date.now();
    try {
      await fn();
    } catch (e) {
      errors.push(`script: ${e.message.split("\n")[0]}`);
    }
    const ms = Date.now() - t0;
    await page.screenshot({ path: path.join(dir, `${name}.png`), animations: "disabled", caret: "hide" });
    report[`${vp.name}/${name}`] = { ms, requests: [...new Set(requests)].sort(), errors };
    console.log(`${vp.name}/${name}: ${ms}ms, ${requests.length} api requests${errors.length ? ", ERRORS: " + errors.join(" | ") : ""}`);
  };

  for (const [name, route] of ROUTES) {
    await shoot(name, async () => {
      await page.goto(`${base}${route}`, { waitUntil: "domcontentloaded" });
      await settle(page);
    });
  }

  // Phone navigation drawer.
  if (vp.name === "phone") {
    await shoot("sidebar-open", async () => {
      await page.goto(`${base}/favorites`, { waitUntil: "domcontentloaded" });
      await settle(page);
      await page.locator("header button").first().click();
      await page.waitForTimeout(500);
    });
  }

  // Viewer: open from a bounded grid, then step with the keyboard.
  const full = 'img[data-testid="full-view"]';
  const decoded = () =>
    page
      .waitForFunction(
        (sel) => {
          const el = document.querySelector(sel);
          return el && el.complete && el.naturalWidth > 0;
        },
        full,
        { timeout: 30000 }
      )
      .catch(() => {});
  await shoot("viewer-open", async () => {
    await page.goto(`${base}/search?q=${encodeURIComponent(search)}`, { waitUntil: "domcontentloaded" });
    await settle(page);
    await page.locator(".photo-grid-item").first().click();
    await page.waitForSelector(full, { timeout: 30000 });
    await decoded();
    await page.waitForTimeout(300);
  });
  await shoot("viewer-next", async () => {
    await page.keyboard.press("ArrowRight");
    await page.waitForTimeout(200);
    await decoded();
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(300);
  });
  await shoot("viewer-info", async () => {
    await page.keyboard.press("i");
    await page.waitForTimeout(400);
  });
  await shoot("viewer-prev", async () => {
    await page.keyboard.press("i");
    await page.keyboard.press("ArrowLeft");
    await page.waitForTimeout(200);
    await decoded();
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(300);
  });
  await shoot("viewer-closed", async () => {
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
    report[`${vp.name}/viewer-closed-url`] = page.url().replace(base, "");
  });

  await ctx.close();
}

await browser.close();
fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2));
console.log(`wrote ${out}`);
