// Diagnostic-only fast-iteration repro for gate-js-heap-runaway (HANDOFF_PLAN §13
// item 8). The real gate (drive_browser.mjs) reproduces the hang somewhere between
// the M6a boot self-check finishing and the M6b inventory-panel checks starting, but
// a full gate run also pays for M6c–M13 + the 30s/120s prebuilt-source timeouts —
// expensive per iteration. This script hits ONLY the boot → first-Co-60-add boundary
// (a fresh browser context per iteration) so a pass/hang pair can be caught in a
// fraction of the wall-clock. Delete this file once the bug is root-caused and fixed.
//
//   node scripts/repro-heap.mjs [N]     # N iterations, default 8

import { spawnSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

const WEB_DIR = path.dirname(fileURLToPath(import.meta.url)) + "/..";
const N = parseInt(process.argv[2], 10) || 8;

function listChromePids() {
  if (process.platform !== "win32") return [];
  const r = spawnSync(
    "powershell.exe",
    [
      "-NoProfile",
      "-Command",
      "(Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' or Name='headless_shell.exe'\" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ProcessId) -join ','",
    ],
    { encoding: "utf8" },
  );
  return (r.stdout || "")
    .trim()
    .split(",")
    .map((s) => parseInt(s, 10))
    .filter(Number.isFinite);
}

function killProcessTree(rootPids) {
  if (process.platform !== "win32" || !rootPids?.length) return;
  spawnSync("powershell.exe", [
    "-NoProfile",
    "-Command",
    `$roots=@(${rootPids.join(",")}); $ids=New-Object System.Collections.Generic.HashSet[int]; foreach($r in $roots){[void]$ids.Add($r)}; $frontier=[int[]]$roots; for($i=0;$i -lt 6;$i++){ if($frontier.Count -eq 0){break}; $filter=($frontier|ForEach-Object{"ParentProcessId=$_"}) -join " or "; $kids=Get-CimInstance Win32_Process -Filter $filter -ErrorAction SilentlyContinue; $next=@(); foreach($k in $kids){ if($ids.Add([int]$k.ProcessId)){$next+=[int]$k.ProcessId} }; $frontier=$next }; foreach($id in $ids){ Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }`,
  ]);
}

function startRssWatcher(rootPids, tag, intervalMs = 1000) {
  if (process.platform !== "win32" || !rootPids?.length) return { stop() {} };
  const script = `
$roots = @(${rootPids.join(",")})
while ($true) {
  try {
    $ids = New-Object System.Collections.Generic.HashSet[int]
    foreach ($r in $roots) { [void]$ids.Add($r) }
    $frontier = [int[]]$roots
    for ($i = 0; $i -lt 6; $i++) {
      if ($frontier.Count -eq 0) { break }
      $filter = ($frontier | ForEach-Object { "ParentProcessId=$_" }) -join " or "
      $kids = Get-CimInstance Win32_Process -Filter $filter -ErrorAction SilentlyContinue
      $next = @()
      foreach ($k in $kids) { if ($ids.Add([int]$k.ProcessId)) { $next += [int]$k.ProcessId } }
      $frontier = $next
    }
    $filter2 = ($ids | ForEach-Object { "ProcessId=$_" }) -join " or "
    $procs = Get-CimInstance Win32_Process -Filter $filter2 -ErrorAction SilentlyContinue
    $sum = ($procs | Measure-Object WorkingSetSize -Sum).Sum
    Write-Output ("RSS[${tag}] " + [DateTime]::UtcNow.ToString("HH:mm:ss.fff") + " n=" + $procs.Count + " MB=" + [math]::Round($sum / 1MB, 1))
  } catch {
    Write-Output ("RSS-ERR[${tag}] " + $_.Exception.Message)
  }
  Start-Sleep -Milliseconds ${intervalMs}
}`;
  const proc = spawn("powershell.exe", ["-NoProfile", "-Command", script]);
  proc.stdout.on("data", (d) => process.stdout.write(`  ${d}`));
  proc.on("error", () => {});
  return {
    stop() {
      try {
        proc.kill();
      } catch {
        /* best-effort */
      }
    },
  };
}

async function launchBrowser() {
  return chromium.launch({ channel: "chromium", headless: true });
}

// Wrap a step so a hang doesn't block the loop forever: log BEFORE issuing (survives
// the freeze), then race against a timeout. On timeout we log it and keep going —
// the browser gets force-killed at the end of the iteration regardless.
async function step(tag, label, fn, timeoutMs = 20_000) {
  console.log(`[${tag}] ${new Date().toISOString()} → ${label}`);
  let timer;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve("TIMEOUT"), timeoutMs);
  });
  const result = await Promise.race([fn().then((v) => ({ v })).catch((e) => ({ e })), timeout]);
  clearTimeout(timer);
  if (result === "TIMEOUT") {
    console.log(`[${tag}] ${new Date().toISOString()} ✗ TIMED OUT waiting on: ${label}`);
    return { hung: true };
  }
  if (result.e) {
    console.log(`[${tag}] ${new Date().toISOString()} ✗ ERROR in ${label}: ${result.e.message}`);
    return { hung: false, error: result.e };
  }
  console.log(`[${tag}] ${new Date().toISOString()} ✓ ${label}`);
  return { hung: false, value: result.v };
}

async function runIteration(i, serverUrl) {
  const tag = `iter${i}`;
  const pidsBefore = listChromePids();
  const browser = await launchBrowser();
  const page = await browser.newPage();
  const launchedPids = listChromePids().filter((p) => !pidsBefore.includes(p));
  const rss = startRssWatcher(launchedPids, tag);
  page.on("console", (m) => console.log(`  [${tag}][page] ${m.text()}`));
  page.on("pageerror", (e) => console.log(`  [${tag}][pageerror] ${e.message}`));

  let hung = false;
  const url = serverUrl + (serverUrl.includes("?") ? "&" : "?") + "selfcheck=1";
  const NAME = ".addrow input.name";
  const QTY = ".addrow input.qty";
  const UNIT = ".addrow select.unit";
  const ADD = ".addrow button";

  // Run a step only if nothing has hung yet, and latch `hung` on timeout/error.
  async function go(label, fn, timeoutMs) {
    if (hung) return;
    const r = await step(tag, label, fn, timeoutMs);
    hung = hung || r.hung;
  }

  await go("goto", () => page.goto(url, { waitUntil: "load" }));
  await go("wait __BOOT_DONE__", () => page.waitForFunction("window.__BOOT_DONE__ === true", null, { timeout: 120_000 }));
  if (!hung) {
    const m6a = await step(tag, "read __M6A_RESULT__", () => page.evaluate("window.__M6A_RESULT__"));
    console.log(`  [${tag}] m6a.ok=${m6a.value?.ok}`);
  }

  // --- Co-60 add (the boundary previously suspected) ---
  await go("fill Co-60 name", () => page.fill(NAME, "Co-60"));
  await go("fill qty 1e9", () => page.fill(QTY, "1e9"));
  await go("select unit Bq", () => page.selectOption(UNIT, "Bq"));
  await go("click Add (Co-60, solve triggered)", () => page.click(ADD));
  await go("wait status==='solved' (Co-60)", () =>
    page.waitForFunction("window.__APP__.status === 'solved'", null, { timeout: 30_000 }),
  );
  await go("wait legend DOM (Co-60)", () => page.waitForSelector('[data-testid="legend"] li'));

  // --- second species (Cs-137, g) — the rest of M6b's own checks, none of which
  // print anything until runM6b() RETURNS in the real gate, so a hang anywhere in
  // here would look identical to the M6a→M6b boundary from the outside. ---
  await go("fill Cs-137 name", () => page.fill(NAME, "Cs-137"));
  await go("fill qty 1", () => page.fill(QTY, "1"));
  await go("select unit g", () => page.selectOption(UNIT, "g"));
  await go("click Add (Cs-137, solve triggered)", () => page.click(ADD));
  await go("wait status==='solved' && closure has Cs-137", () =>
    page.waitForFunction(
      "window.__APP__.status === 'solved' && window.__APP__.closure.includes('Cs-137')",
      null,
      { timeout: 30_000 },
    ),
  );

  // --- handle lifecycle (old handle released, registry_size===1) ---
  await go("handle lifecycle check", () =>
    page.evaluate(() => {
      const app = window.__APP__;
      const b = window.__BRIDGE__;
      const size = b.registry_size();
      return { size: size.ok ? size.size : -1, handle: app.handle };
    }),
  );

  // --- save/load round-trip (setReferenceTimeS, serialize, clear, loadFromText) ---
  await go("save/load round-trip", () =>
    page.evaluate(async () => {
      const app = window.__APP__;
      app.setReferenceTimeS(157788000);
      const before = app.serialize();
      await app.clear();
      const err = await app.loadFromText(before);
      return { err, after: app.serialize() };
    }),
  );

  // --- unknown nuclide → inline error, no solve ---
  await go("fill unknown nuclide name", () => page.fill(NAME, "Zz-000"));
  await go("fill qty 1 (unknown)", () => page.fill(QTY, "1"));
  await go("click Add (unknown, rejected before solve)", () => page.click(ADD));
  await go("wait .inline-error", () => page.waitForSelector(".inline-error"));

  console.log(`[${tag}] ${hung ? "❌ HUNG" : "✅ CLEAN"}`);

  rss.stop();
  await Promise.race([
    browser.close().catch(() => {}),
    new Promise((resolve) => setTimeout(resolve, 10_000)),
  ]);
  killProcessTree(launchedPids); // idempotent — cleans up anything close() missed
  return hung;
}

async function main() {
  console.log("[repro] ensuring runtime archive is current…");
  spawnSync(process.execPath, [path.join(WEB_DIR, "scripts", "build-archive.mjs")], {
    stdio: "inherit",
    cwd: WEB_DIR,
  });

  const { createServer } = await import("vite");
  const server = await createServer({ root: WEB_DIR, server: { port: 0 } });
  await server.listen();
  const url = server.resolvedUrls?.local?.[0];
  console.log(`[repro] serving dev app at ${url}`);

  const results = [];
  for (let i = 1; i <= N; i++) {
    console.log(`\n===== iteration ${i}/${N} =====`);
    const hung = await runIteration(i, url);
    results.push(hung);
    if (hung) {
      console.log(`[repro] caught a hang on iteration ${i} — stopping early for inspection`);
      break;
    }
  }

  console.log("\n===== summary =====");
  results.forEach((h, idx) => console.log(`  iter${idx + 1}: ${h ? "HUNG" : "clean"}`));

  await server.close();
  process.exit(results.some(Boolean) ? 1 : 0);
}

main();
