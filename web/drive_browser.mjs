// M1 headless browser driver.
//
// Serves the repo root over http (so the page can fetch ../engine/*.py), drives
// web/index.html in the installed Chrome (Playwright `chrome` channel — no
// browser download), waits for the in-page bridge checks to finish, prints the
// result, and exits non-zero on failure. This is the real in-WASM evidence for
// M1, the analogue of m0/drive_browser.mjs.
//
// Run: npm install && npm run harness   (from web/)

import http from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

const WEB_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(WEB_DIR, ".."); // repo root: serves both web/ and engine/
const TYPES = {
  ".html": "text/html",
  ".py": "text/plain; charset=utf-8",
  ".mjs": "text/javascript",
  ".js": "text/javascript",
  ".json": "application/json",
};

const server = http.createServer(async (req, res) => {
  try {
    const rel = decodeURIComponent(req.url.split("?")[0]);
    const file = path.join(ROOT, rel === "/" ? "web/index.html" : rel);
    if (!file.startsWith(ROOT)) { res.writeHead(403).end(); return; }
    const body = await readFile(file);
    res.writeHead(200, { "content-type": TYPES[path.extname(file)] || "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404).end("not found");
  }
});

async function launch() {
  for (const channel of ["chrome", "msedge"]) {
    try { return await chromium.launch({ channel, headless: true }); }
    catch { /* channel not installed — try next */ }
  }
  return await chromium.launch({ headless: true });
}

const port = await new Promise((r) => server.listen(0, "127.0.0.1", () => r(server.address().port)));
const url = `http://127.0.0.1:${port}/web/index.html`;
console.log("Serving repo root at " + url);

let exitCode = 1;
let browser;
try {
  browser = await launch();
  const page = await browser.newPage();
  page.on("console", (m) => console.log("  [page] " + m.text()));
  page.on("pageerror", (e) => console.log("  [pageerror] " + e.message));
  await page.goto(url, { waitUntil: "load" });
  await page.waitForFunction("window.__M1_DONE__ === true", null, { timeout: 180_000 });
  const out = await page.evaluate("window.__M1_RESULT__");

  console.log("\n===== M1 RESULT =====");
  console.log(JSON.stringify(out, null, 2));
  exitCode = out && out.ok ? 0 : 1;
  console.log(exitCode === 0 ? "\n✅ M1 PASS (real browser)" : "\n❌ M1 FAIL (real browser)");
} catch (err) {
  console.error("Driver error:", err);
  exitCode = 1;
} finally {
  if (browser) await browser.close();
  server.close();
  process.exit(exitCode);
}
