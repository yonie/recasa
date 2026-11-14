#!/usr/bin/env node
/**
 * Compare two runs of tests/screens.mjs: pixel difference per screenshot
 * (with a diff image where anything changed) and the API requests each page
 * made, so a refactor can show it left both the UI and the API traffic alone.
 *
 *   node tests/compare-screens.mjs /tmp/shots-base /tmp/shots-new /tmp/shots-diff
 *
 * Pixels are compared in a headless browser canvas, so this needs nothing
 * beyond Playwright. A pixel counts as different when any channel differs by
 * more than THRESHOLD (default 24 of 255), which ignores antialiasing noise.
 */
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const [a, b, out = "screens-diff"] = process.argv.slice(2);
if (!a || !b) {
  console.error("usage: compare-screens.mjs <before-dir> <after-dir> [diff-dir]");
  process.exit(2);
}
const threshold = Number(process.env.THRESHOLD || 24);

const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent("<canvas></canvas>");

async function diff(fileA, fileB, fileOut) {
  const toUrl = (f) => `data:image/png;base64,${fs.readFileSync(f).toString("base64")}`;
  const result = await page.evaluate(
    async ([ua, ub, t]) => {
      const load = (src) =>
        new Promise((res, rej) => {
          const img = new Image();
          img.onload = () => res(img);
          img.onerror = rej;
          img.src = src;
        });
      const [ia, ib] = await Promise.all([load(ua), load(ub)]);
      const w = Math.max(ia.width, ib.width);
      const h = Math.max(ia.height, ib.height);
      const ctx = (img) => {
        const c = new OffscreenCanvas(w, h).getContext("2d");
        c.drawImage(img, 0, 0);
        return c.getImageData(0, 0, w, h).data;
      };
      const da = ctx(ia);
      const db = ctx(ib);
      const outCanvas = new OffscreenCanvas(w, h);
      const oc = outCanvas.getContext("2d");
      oc.drawImage(ib, 0, 0);
      const od = oc.getImageData(0, 0, w, h);
      let changed = 0;
      for (let i = 0; i < da.length; i += 4) {
        const d = Math.max(
          Math.abs(da[i] - db[i]),
          Math.abs(da[i + 1] - db[i + 1]),
          Math.abs(da[i + 2] - db[i + 2])
        );
        if (d > t) {
          changed++;
          od.data[i] = 255;
          od.data[i + 1] = 0;
          od.data[i + 2] = 0;
          od.data[i + 3] = 255;
        } else {
          // Fade the unchanged parts so the red stands out.
          od.data[i + 3] = 60;
        }
      }
      oc.putImageData(od, 0, 0);
      const blob = await outCanvas.convertToBlob({ type: "image/png" });
      const buf = new Uint8Array(await blob.arrayBuffer());
      let bin = "";
      for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
      return { changed, total: w * h, sizeMismatch: ia.width !== ib.width || ia.height !== ib.height, png: btoa(bin) };
    },
    [toUrl(fileA), toUrl(fileB), threshold]
  );
  if (result.changed > 0) fs.writeFileSync(fileOut, Buffer.from(result.png, "base64"));
  return result;
}

const rows = [];
for (const vp of fs.readdirSync(a).filter((d) => fs.statSync(path.join(a, d)).isDirectory())) {
  fs.mkdirSync(path.join(out, vp), { recursive: true });
  for (const f of fs.readdirSync(path.join(a, vp)).filter((f) => f.endsWith(".png")).sort()) {
    const fb = path.join(b, vp, f);
    if (!fs.existsSync(fb)) {
      rows.push([`${vp}/${f}`, "missing in after"]);
      continue;
    }
    const r = await diff(path.join(a, vp, f), fb, path.join(out, vp, f));
    const pct = ((100 * r.changed) / r.total).toFixed(2);
    rows.push([`${vp}/${f}`, `${pct}%${r.sizeMismatch ? " (size differs)" : ""}`]);
  }
}
await browser.close();

console.log("\nPixel difference (share of pixels changed):");
for (const [name, v] of rows) console.log(`  ${name.padEnd(34)} ${v}`);

// API requests per page.
const ra = JSON.parse(fs.readFileSync(path.join(a, "report.json"), "utf8"));
const rb = JSON.parse(fs.readFileSync(path.join(b, "report.json"), "utf8"));
console.log("\nAPI requests that differ (- before only, + after only):");
let any = false;
for (const key of Object.keys(ra)) {
  const ea = ra[key];
  const eb = rb[key];
  if (!ea?.requests || !eb?.requests) continue;
  const minus = ea.requests.filter((r) => !eb.requests.includes(r));
  const plus = eb.requests.filter((r) => !ea.requests.includes(r));
  if (minus.length || plus.length) {
    any = true;
    console.log(`  ${key}`);
    for (const r of minus) console.log(`    - ${r}`);
    for (const r of plus) console.log(`    + ${r}`);
  }
}
if (!any) console.log("  none");

console.log("\nErrors in after run:");
const errs = Object.entries(rb).filter(([, v]) => v?.errors?.length);
if (!errs.length) console.log("  none");
for (const [k, v] of errs) console.log(`  ${k}: ${v.errors.join(" | ")}`);

console.log("\nTime to settle, before -> after (ms):");
for (const key of Object.keys(ra)) {
  if (ra[key]?.ms !== undefined && rb[key]?.ms !== undefined) {
    console.log(`  ${key.padEnd(30)} ${String(ra[key].ms).padStart(6)} -> ${String(rb[key].ms).padStart(6)}`);
  }
}
