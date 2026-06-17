// Headless gate — the kill-early bar, extended per M6 chunk.
//
// M6a: boot the real Svelte app + bridge + full dataset in headless Chrome/Edge and
//      round-trip the validated physics benchmarks (the boot self-check, run under
//      ?selfcheck=1 so production boot stays fast).
// M6b: then DRIVE THE INVENTORY PANEL (the rendered app path) — add isotopes, assert
//      the shared-palette legend renders, save/load round-trips EXACTLY, and the
//      no-silent-error contract holds at the UI layer (unknown nuclide → visible
//      error, no handle minted/leaked).
//
//   node drive_browser.mjs            # against the Vite dev server (fast loop)
//   node drive_browser.mjs --built    # against `vite build` + `vite preview`

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

const WEB_DIR = path.dirname(fileURLToPath(import.meta.url));
const BUILT = process.argv.includes("--built");

function ensureArchive() {
  console.log("[gate] ensuring runtime archive is current…");
  const r = spawnSync(process.execPath, [path.join(WEB_DIR, "scripts", "build-archive.mjs")], {
    stdio: "inherit",
    cwd: WEB_DIR,
  });
  if (r.status !== 0) throw new Error("archive build failed");
}

async function startServer() {
  if (BUILT) {
    console.log("[gate] vite build …");
    const { build, preview } = await import("vite");
    await build({ root: WEB_DIR });
    const server = await preview({ root: WEB_DIR, preview: { port: 0 } });
    const url = server.resolvedUrls?.local?.[0];
    if (!url) throw new Error("vite preview produced no URL");
    return { url, close: () => server.httpServer.close() };
  }
  const { createServer } = await import("vite");
  const server = await createServer({ root: WEB_DIR, server: { port: 0 } });
  await server.listen();
  const url = server.resolvedUrls?.local?.[0];
  if (!url) throw new Error("vite dev server produced no URL");
  return { url, close: () => server.close() };
}

async function launchBrowser() {
  for (const channel of ["chrome", "msedge"]) {
    try {
      return await chromium.launch({ channel, headless: true });
    } catch {
      /* channel not installed — try next */
    }
  }
  return await chromium.launch({ headless: true });
}

// --- M6b: drive the inventory panel and assert through the rendered app path ---

async function runM6b(page) {
  const checks = [];
  const record = (name, pass, detail) => checks.push({ name, pass, detail });

  const NAME = ".addrow input.name";
  const QTY = ".addrow input.qty";
  const UNIT = ".addrow select.unit";
  const ADD = ".addrow button";

  // Engine attached + nuclide list loaded (add-by-name source).
  await page.waitForFunction("window.__APP__ && window.__APP__.ready === true", null, {
    timeout: 60_000,
  });
  const nNuclides = await page.evaluate("window.__APP__.availableNuclides.length");
  record("add-by-name list loaded (nuclides() over the bridge)", nNuclides >= 1252, `${nNuclides} nuclides`);

  // 1) Happy path: add Co-60, the panel solves and the palette legend renders.
  await page.fill(NAME, "Co-60");
  await page.fill(QTY, "1e9");
  await page.selectOption(UNIT, "Bq");
  await page.click(ADD);
  await page.waitForFunction("window.__APP__.status === 'solved'", null, { timeout: 30_000 });
  await page.waitForSelector('[data-testid="legend"] li');

  const co = await page.evaluate(() => {
    const app = window.__APP__;
    return { closure: app.closure, colors: { ...app.colors }, handle: app.handle };
  });
  record(
    "Co-60 add → solved closure with shared colors",
    co.closure.includes("Co-60") &&
      co.closure.includes("Ni-60") &&
      typeof co.colors["Co-60"] === "string" &&
      co.colors["Co-60"].length > 0 &&
      typeof co.handle === "string",
    `closure=[${co.closure.join(", ")}], Co-60 color=${co.colors["Co-60"]}`,
  );

  // The legend actually rendered swatches in the DOM (not just store state).
  const legendCount = await page.locator('[data-testid="legend"] li').count();
  const swatchBg = await page
    .locator('[data-testid="legend"] li .swatch')
    .first()
    .evaluate((el) => getComputedStyle(el).backgroundColor);
  record(
    "legend swatches rendered in the DOM",
    legendCount >= 2 && swatchBg !== "" && swatchBg !== "rgba(0, 0, 0, 0)",
    `${legendCount} legend items, first swatch bg=${swatchBg}`,
  );

  // 2) Add a second species in a different unit; colors stay distinct + stable.
  await page.fill(NAME, "Cs-137");
  await page.fill(QTY, "1");
  await page.selectOption(UNIT, "g");
  await page.click(ADD);
  await page.waitForFunction(
    "window.__APP__.status === 'solved' && window.__APP__.closure.includes('Cs-137')",
    null,
    { timeout: 30_000 },
  );
  const two = await page.evaluate(() => {
    const app = window.__APP__;
    return { closure: app.closure, colors: { ...app.colors }, nEntries: app.entries.length };
  });
  record(
    "second species (Cs-137, g) → distinct + stable colors",
    two.closure.includes("Cs-137") &&
      two.closure.includes("Ba-137m") &&
      two.colors["Co-60"] === co.colors["Co-60"] && // Co-60's color unchanged across re-solve
      two.colors["Cs-137"] !== two.colors["Co-60"] &&
      two.nEntries === 2,
    `Cs-137 color=${two.colors["Cs-137"]}, Co-60 stable=${two.colors["Co-60"] === co.colors["Co-60"]}`,
  );

  // 2b) Handle lifecycle (#2) — PROVE the old handle was released and exactly one is
  // live, by reusing the pre-re-solve handle (must be dead) + the leak canary. The
  // Zz-000 check below is rejected client-side, so it cannot exercise this path.
  const life = await page.evaluate((h1) => {
    const b = window.__BRIDGE__;
    const old = b.evaluate(h1, { times_s: [0.0] }); // released handle → ok:false
    const size = b.registry_size();
    return { oldDead: old.ok === false, size: size.ok ? size.size : -1, h2: window.__APP__.handle };
  }, co.handle);
  record(
    "handle lifecycle: old handle released, exactly one live (#2)",
    life.oldDead && life.size === 1 && life.h2 !== co.handle,
    `oldHandleDead=${life.oldDead}, registry_size=${life.size}, newHandle≠old=${life.h2 !== co.handle}`,
  );

  // 3) Save / load round-trip — EXACT equality (order, numeric type, unit, precision, t=0).
  const rt = await page.evaluate(async () => {
    const app = window.__APP__;
    app.setReferenceTimeS(157788000); // 5 yr, to prove t=0 round-trips
    const before = app.serialize();
    const beforeEntries = JSON.parse(JSON.stringify(app.entries));
    const beforePrec = app.precision;
    const beforeT0 = app.referenceTimeS;
    await app.clear();
    const clearedEmpty = app.entries.length === 0 && app.handle === null;
    const loadErr = await app.loadFromText(before);
    const after = app.serialize();
    return {
      identical: before === after,
      loadErr,
      clearedEmpty,
      beforeEntries,
      afterEntries: JSON.parse(JSON.stringify(app.entries)),
      precOk: app.precision === beforePrec,
      t0Ok: app.referenceTimeS === beforeT0,
    };
  });
  const entriesExact =
    JSON.stringify(rt.beforeEntries) === JSON.stringify(rt.afterEntries) &&
    rt.afterEntries.every((e) => typeof e.quantity === "number");
  record(
    "save/load round-trip is exact (order, number, unit, precision, t₀)",
    rt.identical && rt.loadErr === null && rt.clearedEmpty && entriesExact && rt.precOk && rt.t0Ok,
    `identical=${rt.identical}, entriesExact=${entriesExact}, prec=${rt.precOk}, t0=${rt.t0Ok}`,
  );

  // 4) UI no-silent-error (#3): an unknown nuclide surfaces a VISIBLE inline error and
  // is rejected before any solve (entries + handle untouched). (Handle release itself
  // is proven in 2b; the bridge's loud EngineError path is proven in the boot check.)
  const handleBefore = await page.evaluate("window.__APP__.handle");
  const nBefore = await page.evaluate("window.__APP__.entries.length");
  await page.fill(NAME, "Zz-000");
  await page.fill(QTY, "1");
  await page.click(ADD);
  await page.waitForSelector(".inline-error");
  const errText = await page.locator(".inline-error").innerText();
  const post = await page.evaluate("({ handle: window.__APP__.handle, n: window.__APP__.entries.length })");
  record(
    "unknown nuclide → visible inline error, rejected before solve (#3)",
    /unknown nuclide/i.test(errText) && post.handle === handleBefore && post.n === nBefore,
    `error=${JSON.stringify(errText)}, handleUnchanged=${post.handle === handleBefore}, entriesUnchanged=${post.n === nBefore}`,
  );

  return { ok: checks.every((c) => c.pass), checks };
}

let exitCode = 1;
let browser;
let server;
try {
  ensureArchive();
  server = await startServer();
  console.log(`[gate] serving ${BUILT ? "built" : "dev"} app at ${server.url}`);

  browser = await launchBrowser();
  const page = await browser.newPage();
  page.on("console", (m) => console.log("  [page] " + m.text()));
  page.on("pageerror", (e) => console.log("  [pageerror] " + e.message));

  // ?selfcheck=1 runs the M6a boot self-check (the kill-early benchmarks).
  const url = server.url + (server.url.includes("?") ? "&" : "?") + "selfcheck=1";
  await page.goto(url, { waitUntil: "load" });
  await page.waitForFunction("window.__BOOT_DONE__ === true", null, { timeout: 240_000 });

  const m6a = await page.evaluate("window.__M6A_RESULT__");
  console.log("\n===== M6a boot self-check =====");
  console.log(JSON.stringify(m6a, null, 2));
  const m6aOk = !!(m6a && m6a.ok);

  let m6b = { ok: false, checks: [] };
  if (m6aOk) {
    m6b = await runM6b(page);
  } else {
    console.log("[gate] skipping M6b — boot self-check failed");
  }

  console.log("\n===== M6b inventory panel =====");
  for (const c of m6b.checks) {
    console.log(`  ${c.pass ? "✓" : "✗"} ${c.name} — ${c.detail}`);
  }

  exitCode = m6aOk && m6b.ok ? 0 : 1;
  console.log(
    exitCode === 0
      ? "\n✅ M6b PASS (real browser): boot benchmarks + inventory panel + save/load"
      : "\n❌ M6b FAIL (real browser)",
  );
} catch (err) {
  console.error("Driver error:", err);
  exitCode = 1;
} finally {
  if (browser) await browser.close();
  if (server) await server.close();
  process.exit(exitCode);
}
