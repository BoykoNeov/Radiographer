// M0 headless browser driver.
//
// Serves m0/ over http (so the harness can fetch smoke.py), drives index.html in
// a real Chromium-family browser (the installed Chrome, via Playwright's `chrome`
// channel — no browser binary download), waits for the in-page smoke test to
// finish, prints the result, and exits non-zero on failure.
//
// This is the *real* M0 evidence: real WASM engine, real CDN load, real timing.
// Run: npm run smoke:browser   (from m0/)

import http from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

const DIR = path.dirname(fileURLToPath(import.meta.url));
const TYPES = { ".html": "text/html", ".py": "text/plain; charset=utf-8", ".mjs": "text/javascript", ".json": "application/json" };

const server = http.createServer(async (req, res) => {
  try {
    const rel = decodeURIComponent(req.url.split("?")[0]);
    const file = path.join(DIR, rel === "/" ? "index.html" : rel);
    if (!file.startsWith(DIR)) { res.writeHead(403).end(); return; }
    const body = await readFile(file);
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404).end("not found");
  }
});

async function launch() {
  // Prefer the installed Chrome; fall back to Edge; finally Playwright's bundled
  // Chromium (only present if browsers were downloaded). chromium.launch is async,
  // so each attempt must be awaited inside the try or the rejection escapes it.
  for (const channel of ["chrome", "msedge"]) {
    try { return await chromium.launch({ channel, headless: true }); }
    catch { /* channel not installed — try next */ }
  }
  return await chromium.launch({ headless: true });
}

const port = await new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server.address().port)));
const url = `http://127.0.0.1:${port}/index.html`;
console.log("Serving m0/ at " + url);

let exitCode = 1;
let browser;
try {
  browser = await launch();
  const page = await browser.newPage();
  page.on("console", (m) => console.log("  [page] " + m.text()));
  page.on("pageerror", (e) => console.log("  [pageerror] " + e.message));
  await page.goto(url, { waitUntil: "load" });

  // First load downloads tens of MB of WASM from the CDN — give it room.
  await page.waitForFunction("window.__M0_DONE__ === true", null, { timeout: 180_000 });
  const out = await page.evaluate("window.__M0_RESULT__");

  console.log("\n===== M0 RESULT =====");
  console.log(JSON.stringify(out, null, 2));
  exitCode = out && out.ok ? 0 : 1;
  console.log(exitCode === 0 ? "\n✅ M0 PASS (real browser)" : "\n❌ M0 FAIL (real browser)");
} catch (err) {
  console.error("Driver error:", err);
  exitCode = 1;
} finally {
  if (browser) await browser.close();
  server.close();
  process.exit(exitCode);
}
