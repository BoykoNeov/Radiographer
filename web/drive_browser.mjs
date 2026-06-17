// Headless gate — the kill-early bar, extended per M6 chunk.
//
// M6a: boot the real Svelte app + bridge + full dataset in headless Chrome/Edge and
//      round-trip the validated physics benchmarks (the boot self-check, run under
//      ?selfcheck=1 so production boot stays fast).
// M6b: then DRIVE THE INVENTORY PANEL (the rendered app path) — add isotopes, assert
//      the shared-palette legend renders, save/load round-trips EXACTLY, and the
//      no-silent-error contract holds at the UI layer (unknown nuclide → visible
//      error, no handle minted/leaked).
// M6c: then the overlay curves through the rendered Plotly path (secular-equilibrium
//      ratio off the drawn trace, axis toggle = evaluate-not-resolve, per-axis floor).
// M6d: then the time control — log slider + half-life ticks, cursor via relayout, the
//      source-age OFFSET CONTRACT (t₀=t½ ⇒ rendered ratio 0.5), and animate.
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

// --- M6c: drive the overlay curves and assert through the RENDERED Plotly path --
//
// "Through the rendered app path" (M6-ui) is taken literally: every assertion reads
// the Plotly div's own `.data`/`.layout` (what the user sees), not the store. The
// physics anchor is the Cs-137 secular-equilibrium ratio recovered from the drawn
// trace; the M6c invariants proven are (a) axis toggle re-evaluates but NEVER
// re-solves (#1), and (b) per-axis flooring (a stable end-product is an honest gap
// on Activity yet grows in on Atoms).

const PLOT = '[data-testid="curves-plot"]';

async function runM6c(page) {
  const checks = [];
  const record = (name, pass, detail) => checks.push({ name, pass, detail });

  // Reset to a clean, known inventory: Cs-137 only, Activity (Bq), log y. This still
  // flows solve → recomputeCurves → $effect → Plotly.react (the real render path).
  await page.evaluate(async () => {
    const app = window.__APP__;
    await app.clear();
    app.setReferenceTimeS(0); // M6b's round-trip left t₀=5 yr; reset for a clean baseline
    app.setAxis("activity");
    app.setLogY(true);
    await app.addEntry("Cs-137", 1.0e9, "Bq");
  });
  await page.waitForFunction(
    "window.__APP__.status === 'solved' && window.__APP__.curve && window.__APP__.curve.axis === 'activity'",
    null,
    { timeout: 30_000 },
  );
  // Wait for Plotly to have rendered the Activity-axis traces into the div.
  await page.waitForFunction(
    `(() => { const el = document.querySelector('${PLOT}');
       return el && el.data && el.data.length >= 2 &&
         el.layout && el.layout.yaxis && el.layout.yaxis.title &&
         el.layout.yaxis.title.text === 'Activity (Bq)'; })()`,
    null,
    { timeout: 30_000 },
  );

  // 1) The overlay rendered one trace per closure member, in the shared palette,
  //    with the §12 y-axis label.
  const drawn = await page.evaluate((sel) => {
    const app = window.__APP__;
    const el = document.querySelector(sel);
    const data = el.data;
    const names = data.map((d) => d.name);
    const colorsMatch = data.every((d) => d.line && d.line.color === app.colors[d.name]);
    return {
      n: data.length,
      names,
      closure: app.closure,
      colorsMatch,
      yTitle: el.layout.yaxis.title.text,
      xType: el.layout.xaxis.type,
      yType: el.layout.yaxis.type,
    };
  }, PLOT);
  record(
    "overlay renders one trace per closure member, shared palette, §12 label",
    drawn.n === drawn.closure.length &&
      drawn.names.includes("Cs-137") &&
      drawn.names.includes("Ba-137m") &&
      drawn.colorsMatch &&
      drawn.yTitle === "Activity (Bq)" &&
      drawn.xType === "log" &&
      drawn.yType === "log",
    `traces=${drawn.n} [${drawn.names.join(", ")}], colorsMatch=${drawn.colorsMatch}, ` +
      `yTitle=${JSON.stringify(drawn.yTitle)}, axes=${drawn.xType}/${drawn.yType}`,
  );

  // 2) PHYSICS through the rendered trace: Cs-137 secular equilibrium
  //    A(Ba-137m)/A(Cs-137) ≈ 0.94399 read off the drawn curve nearest 1 d. The
  //    plateau is flat (minutes→years) so the nearest log-grid point is within ~1%.
  const eq = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const byName = Object.fromEntries(el.data.map((d) => [d.name, d]));
    const cs = byName["Cs-137"];
    const ba = byName["Ba-137m"];
    const xs = cs.x;
    let j = 0;
    let best = Infinity;
    for (let i = 0; i < xs.length; i++) {
      const dd = Math.abs(Math.log10(xs[i]) - Math.log10(86400));
      if (dd < best) {
        best = dd;
        j = i;
      }
    }
    return { t: xs[j], ratio: ba.y[j] / cs.y[j] };
  }, PLOT);
  record(
    "Cs-137 secular equilibrium ≈ 0.94399 read off the RENDERED curve",
    Math.abs(eq.ratio - 0.94399) <= 0.94399 * 0.01,
    `ratio=${eq.ratio?.toFixed(5)} @ t≈${eq.t?.toExponential(2)} s (nearest 1 d)`,
  );

  // 3) Axis toggle = EVALUATE, never re-solve (#1). Click the rendered "Atoms"
  //    button; the handle must be unchanged and exactly one inventory stays live.
  const before = await page.evaluate(() => ({
    handle: window.__APP__.handle,
    size: (() => {
      const s = window.__BRIDGE__.registry_size();
      return s.ok ? s.size : -1;
    })(),
  }));
  await page.getByRole("button", { name: "Atoms", exact: true }).click();
  await page.waitForFunction(
    `(() => { const el = document.querySelector('${PLOT}');
       return window.__APP__.curve && window.__APP__.curve.axis === 'atoms' &&
         el.layout.yaxis.title.text === 'Atoms'; })()`,
    null,
    { timeout: 30_000 },
  );
  const after = await page.evaluate(() => ({
    handle: window.__APP__.handle,
    size: (() => {
      const s = window.__BRIDGE__.registry_size();
      return s.ok ? s.size : -1;
    })(),
    axis: window.__APP__.curve.axis,
  }));
  record(
    "axis toggle re-evaluates, never re-solves (#1): handle stable, 1 live",
    after.handle === before.handle && after.size === 1 && before.size === 1 && after.axis === "atoms",
    `handleStable=${after.handle === before.handle}, registry_size=${before.size}→${after.size}, axis=${after.axis}`,
  );

  // 4) Per-axis flooring (§9): the stable end-product (Ba-137, t½=∞) is an honest
  //    GAP on Activity (zero activity → all null) yet GROWS IN on Atoms — same
  //    nuclide, two axes, two visibilities. This catches a per-series-floor bug the
  //    ratio check (Ba-137m is never floored) cannot.
  const onAtoms = await page.evaluate((sel) => {
    const app = window.__APP__;
    const hl = app.solveMeta.half_lives_s;
    const stable = app.closure.find((n) => hl[n] === null) ?? null;
    const el = document.querySelector(sel);
    const tr = el.data.find((d) => d.name === stable);
    const ys = (tr ? tr.y : []).filter((v) => v !== null && Number.isFinite(v));
    return { stable, hasGrowth: ys.length > 1 && ys[ys.length - 1] > ys[0] && ys[ys.length - 1] > 0 };
  }, PLOT);
  // Switch back to Activity and assert the same stable trace is fully floored out.
  await page.getByRole("button", { name: "Activity", exact: true }).click();
  await page.waitForFunction(
    `(() => { const el = document.querySelector('${PLOT}');
       return window.__APP__.curve && window.__APP__.curve.axis === 'activity' &&
         el.layout.yaxis.title.text === 'Activity (Bq)'; })()`,
    null,
    { timeout: 30_000 },
  );
  const onActivity = await page.evaluate(
    (args) => {
      const [sel, stable] = args;
      const el = document.querySelector(sel);
      const tr = el.data.find((d) => d.name === stable);
      const ys = tr ? tr.y : [];
      return { allNull: ys.length > 0 && ys.every((v) => v === null) };
    },
    [PLOT, onAtoms.stable],
  );
  record(
    "per-axis flooring: stable end-product is a gap on Activity, grows on Atoms",
    onAtoms.stable !== null && onAtoms.hasGrowth && onActivity.allNull,
    `stable=${onAtoms.stable}, atoms.growing=${onAtoms.hasGrowth}, activity.allNull=${onActivity.allNull}`,
  );

  // 5) Mass axis + secondary-unit SWITCH = evaluate (label tracks unit, §12), never
  //    re-solve (#1). Closes the third toggle leg (Mass is a distinct engine branch:
  //    N·atomic_masses/AVOGADRO) and the unit-change path the axis-only check misses.
  const h0 = await page.evaluate(() => window.__APP__.handle);
  await page.getByRole("button", { name: "Mass", exact: true }).click();
  await page.waitForFunction(`document.querySelector('${PLOT}').layout.yaxis.title.text === 'Mass (g)'`, null, {
    timeout: 30_000,
  });
  await page.selectOption('[data-testid="curve-unit"]', "kg");
  await page.waitForFunction(`document.querySelector('${PLOT}').layout.yaxis.title.text === 'Mass (kg)'`, null, {
    timeout: 30_000,
  });
  const mass = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const app = window.__APP__;
    const s = window.__BRIDGE__.registry_size();
    return { traces: el.data.length, handle: app.handle, size: s.ok ? s.size : -1, unit: app.curve.unit };
  }, PLOT);
  record(
    "mass axis + unit switch: label tracks unit (§12), evaluate not re-solve (#1)",
    mass.traces === 3 && mass.handle === h0 && mass.size === 1 && mass.unit === "kg",
    `traces=${mass.traces}, handleStable=${mass.handle === h0}, size=${mass.size}, unit=${mass.unit}`,
  );

  return { ok: checks.every((c) => c.pass), checks };
}

// --- M6d: drive the time control (slider + cursor + source-age offset + animate) -
//
// The load-bearing assertion is the OFFSET CONTRACT (advisor): the source-age t₀ is
// added at evaluate time, so the rendered curve is the source decayed by t₀. We set
// t₀ = Cs-137's half-life and read the SAME display-time point with t₀=0 vs t₀=t½:
// A(t₀+x)/A(x) = exp(-λt₀) = 0.5 EXACTLY (the display point x cancels). This is what
// de-risks M6f's dose calc, which reads `currentTimeS = referenceTimeS + cursorOffsetS`.
// The cursor-move check proves it's a Plotly relayout (handle stable, 1 live), not a
// re-solve; animate proves the sweep advances, stops, and leaks no handle.

async function runM6d(page) {
  const checks = [];
  const record = (name, pass, detail) => checks.push({ name, pass, detail });

  // Clean baseline: Cs-137 only, Activity, log y, t₀=0. (Cs-137→Ba-137m→Ba-137:
  // two finite-half-life species + one stable end-product.)
  await page.evaluate(async () => {
    const app = window.__APP__;
    await app.clear();
    app.setReferenceTimeS(0);
    app.setAxis("activity");
    app.setLogY(true);
    await app.addEntry("Cs-137", 1.0e9, "Bq");
  });
  await page.waitForFunction(
    "window.__APP__.status === 'solved' && window.__APP__.curve && window.__APP__.cursorRange",
    null,
    { timeout: 30_000 },
  );
  await page.waitForSelector('[data-testid="time-control"]');
  await page.waitForSelector('[data-testid="time-slider"]');

  // 1) Slider spans the display auto-range; one half-life tick per finite species.
  const slider = await page.evaluate(() => {
    const app = window.__APP__;
    const el = document.querySelector('[data-testid="time-slider"]');
    const ticks = document.querySelectorAll('[data-testid="halflife-ticks"] .tick');
    const r = app.cursorRange;
    return {
      min: parseFloat(el.min),
      max: parseFloat(el.max),
      wantMin: Math.log10(r[0]),
      wantMax: Math.log10(r[1]),
      nTicks: ticks.length,
      closure: app.closure,
    };
  });
  record(
    "log slider spans the display auto-range; one half-life tick per finite species",
    Math.abs(slider.min - slider.wantMin) < 1e-6 &&
      Math.abs(slider.max - slider.wantMax) < 1e-6 &&
      slider.nTicks === 2, // Cs-137 + Ba-137m finite; Ba-137 stable → no tick
    `slider=[${slider.min.toFixed(2)},${slider.max.toFixed(2)}] want=[${slider.wantMin.toFixed(2)},${slider.wantMax.toFixed(2)}], ticks=${slider.nTicks} of closure [${slider.closure.join(", ")}]`,
  );

  // 2) The cursor is a Plotly relayout, NOT a re-solve. Move the slider through the
  //    rendered DOM; assert the vline shape follows (read layout.shapes), the handle
  //    is unchanged and exactly one inventory stays live (#1/#2).
  const beforeMove = await page.evaluate(() => ({
    handle: window.__APP__.handle,
    size: (() => {
      const s = window.__BRIDGE__.registry_size();
      return s.ok ? s.size : -1;
    })(),
  }));
  const target = await page.evaluate(() => {
    const r = window.__APP__.cursorRange;
    return Math.sqrt(r[0] * r[1]) * 5; // a point distinct from the default home
  });
  await page.$eval(
    '[data-testid="time-slider"]',
    (el, logv) => {
      el.value = String(logv);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    },
    Math.log10(target),
  );
  await page.waitForFunction(
    (t) => {
      const el = document.querySelector('[data-testid="curves-plot"]');
      const sh = el && el.layout && el.layout.shapes;
      return sh && sh.length >= 1 && Math.abs(sh[0].x0 - t) / t < 0.02;
    },
    target,
    { timeout: 30_000 },
  );
  const afterMove = await page.evaluate(() => {
    const el = document.querySelector('[data-testid="curves-plot"]');
    return {
      cursor: window.__APP__.cursorOffsetS,
      shapeX: el.layout.shapes[0].x0,
      handle: window.__APP__.handle,
      size: (() => {
        const s = window.__BRIDGE__.registry_size();
        return s.ok ? s.size : -1;
      })(),
    };
  });
  record(
    "cursor moves via Plotly relayout (vline follows), no re-solve (#1/#2)",
    Math.abs(afterMove.cursor - target) / target < 0.02 &&
      Math.abs(afterMove.shapeX - afterMove.cursor) / afterMove.cursor < 1e-6 &&
      afterMove.handle === beforeMove.handle &&
      beforeMove.size === 1 &&
      afterMove.size === 1,
    `cursor=${afterMove.cursor.toExponential(2)}≈target=${target.toExponential(2)}, shapeX==cursor, handleStable=${afterMove.handle === beforeMove.handle}, size=${beforeMove.size}→${afterMove.size}`,
  );

  // 3) THE OFFSET CONTRACT (M6f de-risk): t₀ is added at evaluate time, so the curve
  //    is the source aged by t₀. Read Cs-137's RENDERED y at a fixed display point
  //    with t₀=0, then t₀=t½(Cs-137); the ratio must be exp(-λt½)=0.5 exactly. Also
  //    assert currentTimeS = referenceTimeS + cursorOffsetS and it's an evaluate, not
  //    a re-solve.
  const PLOT_SEL = '[data-testid="curves-plot"]';
  const readCsAtDay = () =>
    page.evaluate((sel) => {
      const el = document.querySelector(sel);
      const cs = el.data.find((d) => d.name === "Cs-137");
      const xs = cs.x; // display grid (curveX)
      let j = 0,
        best = Infinity;
      for (let i = 0; i < xs.length; i++) {
        const dd = Math.abs(Math.log10(xs[i]) - Math.log10(86400));
        if (dd < best) {
          best = dd;
          j = i;
        }
      }
      return { y: cs.y[j], x: xs[j] };
    }, PLOT_SEL);

  const y0 = await readCsAtDay(); // t₀ = 0
  const offsetState = await page.evaluate(() => {
    const app = window.__APP__;
    const halfLife = app.solveMeta.half_lives_s["Cs-137"]; // exact rd seconds
    const beforeHandle = app.handle;
    const beforeSize = (() => {
      const s = window.__BRIDGE__.registry_size();
      return s.ok ? s.size : -1;
    })();
    app.setReferenceTimeS(halfLife);
    return {
      halfLife,
      beforeHandle,
      beforeSize,
      afterHandle: app.handle,
      afterSize: (() => {
        const s = window.__BRIDGE__.registry_size();
        return s.ok ? s.size : -1;
      })(),
      currentTimeS: app.currentTimeS,
      sumCheck: app.referenceTimeS + app.cursorOffsetS,
    };
  });
  await page.waitForFunction(
    "window.__APP__.curve && window.__APP__.referenceTimeS > 0",
    null,
    { timeout: 30_000 },
  );
  const y1 = await readCsAtDay(); // t₀ = t½
  const ratio = y1.y / y0.y;
  record(
    "OFFSET CONTRACT: t₀=t½ ⇒ rendered A(t₀+x)/A(x)=exp(-λt½)=0.5 (source aged by t₀)",
    Math.abs(ratio - 0.5) < 1e-3 &&
      Math.abs(offsetState.currentTimeS - offsetState.sumCheck) < 1e-6 &&
      offsetState.afterHandle === offsetState.beforeHandle &&
      offsetState.beforeSize === 1 &&
      offsetState.afterSize === 1,
    `ratio=${ratio.toFixed(5)} (want 0.5), currentTimeS=referenceTimeS+cursorOffsetS=${offsetState.currentTimeS.toExponential(3)}, offset is evaluate not re-solve (handleStable=${offsetState.afterHandle === offsetState.beforeHandle}, size=${offsetState.beforeSize}→${offsetState.afterSize})`,
  );

  // Reset t₀ back to 0 for the animate check.
  await page.evaluate(() => window.__APP__.setReferenceTimeS(0));

  // 4) Animate sweeps the cursor (an evaluate-free relayout loop), then stops with no
  //    handle leak. Each frame is a cursor move, NOT a re-solve (§3); pausing tears
  //    the loop down (advisor: an orphaned loop is a silent-error vector).
  const animBefore = await page.evaluate(() => ({
    handle: window.__APP__.handle,
    cursor: window.__APP__.cursorOffsetS,
    size: (() => {
      const s = window.__BRIDGE__.registry_size();
      return s.ok ? s.size : -1;
    })(),
  }));
  await page.click('[data-testid="time-play"]');
  // Let several frames run (40 ms each), then confirm the cursor advanced.
  await page.waitForFunction(
    (c0) => window.__APP__.animating === true && window.__APP__.cursorOffsetS > c0,
    animBefore.cursor,
    { timeout: 30_000 },
  );
  const animMid = await page.evaluate(() => ({
    animating: window.__APP__.animating,
    cursor: window.__APP__.cursorOffsetS,
  }));
  await page.click('[data-testid="time-play"]'); // pause
  await page.waitForFunction("window.__APP__.animating === false", null, { timeout: 30_000 });
  const animAfter = await page.evaluate(() => ({
    animating: window.__APP__.animating,
    cursor: window.__APP__.cursorOffsetS,
    handle: window.__APP__.handle,
    size: (() => {
      const s = window.__BRIDGE__.registry_size();
      return s.ok ? s.size : -1;
    })(),
  }));
  record(
    "animate sweeps the cursor then stops, no re-solve, no handle leak (§3/#2)",
    animMid.animating === true &&
      animMid.cursor > animBefore.cursor &&
      animAfter.animating === false &&
      animAfter.handle === animBefore.handle &&
      animAfter.size === 1,
    `advanced ${animBefore.cursor.toExponential(2)}→${animMid.cursor.toExponential(2)}, stopped=${!animAfter.animating}, handleStable=${animAfter.handle === animBefore.handle}, size=${animAfter.size}`,
  );

  return { ok: checks.every((c) => c.pass), checks };
}

// --- M6f: drive the dose calculator + breakdown through the rendered app path ----
//
// The load-bearing benchmark (advisor): Co-60 H*(10)@1 m read OFF THE RENDERED γ card
// must equal an independent bridge dose() call AND sit in the M3 physical band — the
// UI plumbs the validated number, not a fabricated one (§11). The honesty invariants:
// the dose path is a PURE EVALUATE (registry stays 1 across a distance change, §3/#1);
// γ(Sv) and β(Gy/Hp(0.07)) ride SEPARATE axes and are never summed (§6.2 LOCKED);
// neutron is grayed for a user inventory (§6.3); and accumulated dose INTEGRATES the
// rate, not rate×time (§11) — proven with a short-lived source over one half-life.

async function runM6f(page) {
  const checks = [];
  const record = (name, pass, detail) => checks.push({ name, pass, detail });

  const DOSE = '[data-testid="dose"]';
  const DIST = '[data-testid="dose-distance"]';
  const GAMMA = '[data-testid="dose-gamma"]';
  const NEUTRON = '[data-testid="dose-neutron"]';
  const DPLOT = '[data-testid="dose-plot"]';

  // Clean baseline: Co-60 1 GBq (the gamma-dose reference case), t₀=0, H*(10) @ 1 m,
  // cursor homed to the low end of the range so the source is ~full activity.
  await page.evaluate(async () => {
    const app = window.__APP__;
    await app.clear();
    app.setReferenceTimeS(0);
    app.setDoseQuantity("ambient_H10");
    app.setDoseDistanceM(1.0);
    await app.addEntry("Co-60", 1.0e9, "Bq");
    app.setCursorOffsetS(0); // clamps to the range lo → Co-60 ≈ 1 GBq
  });
  await page.waitForFunction(
    "window.__APP__.status === 'solved' && window.__APP__.gammaDoseSeries && window.__APP__.curveX.length > 0",
    null,
    { timeout: 30_000 },
  );
  await page.waitForSelector(DOSE);
  await page.waitForSelector(DPLOT);
  await page.waitForFunction(
    (sel) => {
      const el = document.querySelector(sel);
      return el && el.data && el.data.length === 2; // γ + β traces reacted
    },
    DPLOT,
    { timeout: 30_000 },
  );

  // 1) Co-60 H*(10)@1 m benchmark THROUGH the rendered γ card. The rendered value
  //    (data-rate-si, Sv/s) must equal an independent dose() call, and the source's
  //    air-kerma constant must reproduce ≈0.308 mGy·m²·GBq⁻¹·h⁻¹ with H*(10)/Kₐ
  //    physical (M3 test_dose_gamma, now live through the handle).
  const bench = await page.evaluate(
    (sel) => {
      const app = window.__APP__;
      const br = window.__BRIDGE__;
      const t = app.currentTimeS;
      const h = app.handle;
      const renderedH10 = parseFloat(
        document.querySelector(sel).getAttribute("data-rate-si"),
      ); // Sv/s
      const h10 = br.dose(h, { times_s: [t], quantity: "ambient_H10", distance_m: 1.0 });
      const ka = br.dose(h, { times_s: [t], quantity: "air_kerma", distance_m: 1.0 });
      const act = br.evaluate(h, { times_s: [t], axis: "activity", unit: "Bq" });
      const aBq = act.ok ? act.series["Co-60"][0] : NaN;
      const kaSi = ka.ok ? ka.rate_si[0] : NaN;
      const h10Si = h10.ok ? h10.rate_si[0] : NaN;
      return {
        renderedH10,
        h10Si,
        kaSi,
        ratio: h10Si / kaSi,
        mGyh_perGBq: (kaSi * 1000 * 3600) / (aBq / 1e9),
      };
    },
    GAMMA,
  );
  record(
    "Co-60 H*(10)@1m benchmark off the RENDERED γ card == dose() AND in M3 band (§11)",
    Math.abs(bench.renderedH10 - bench.h10Si) / bench.h10Si < 1e-6 &&
      Math.abs(bench.mGyh_perGBq - 0.308) / 0.308 < 0.05 &&
      bench.ratio > 1.05 &&
      bench.ratio < 1.3,
    `rendered=${bench.renderedH10.toExponential(4)} Sv/s == dose()=${bench.h10Si.toExponential(4)}, ` +
      `Kₐ=${bench.mGyh_perGBq.toFixed(4)} mGy·m²·GBq⁻¹·h⁻¹ (want 0.308), H*(10)/Kₐ=${bench.ratio.toFixed(3)}`,
  );

  // 2) Distance 1→2 m through the rendered input: pure evaluate (handle stable,
  //    registry stays 1, NEVER routes through solve()), and inverse-square renders
  //    (rate drops 4×). The dose is "evaluate many" off one solve (§3/#1/#2).
  const before = await page.evaluate((sel) => {
    const s = window.__BRIDGE__.registry_size();
    return {
      handle: window.__APP__.handle,
      size: s.ok ? s.size : -1,
      rate: parseFloat(document.querySelector(sel).getAttribute("data-rate-si")),
    };
  }, GAMMA);
  await page.fill(DIST, "2");
  await page.press(DIST, "Enter");
  await page.waitForFunction("window.__APP__.doseDistanceM === 2", null, { timeout: 30_000 });
  const after = await page.evaluate((sel) => {
    const s = window.__BRIDGE__.registry_size();
    return {
      handle: window.__APP__.handle,
      size: s.ok ? s.size : -1,
      rate: parseFloat(document.querySelector(sel).getAttribute("data-rate-si")),
    };
  }, GAMMA);
  record(
    "distance 1→2 m: pure evaluate (handle stable, registry==1), inverse-square renders 4×",
    after.handle === before.handle &&
      before.size === 1 &&
      after.size === 1 &&
      Math.abs(before.rate / after.rate - 4.0) / 4.0 < 0.01,
    `handleStable=${after.handle === before.handle}, size=${before.size}→${after.size}, rate1/rate2=${(before.rate / after.rate).toFixed(3)} (want 4)`,
  );
  await page.fill(DIST, "1"); // restore for the remaining checks
  await page.press(DIST, "Enter");
  await page.waitForFunction("window.__APP__.doseDistanceM === 1", null, { timeout: 30_000 });

  // 3) γ(Sv) and β(Gy/Hp(0.07)) are DIFFERENT quantities — separate engine series and
  //    SEPARATE plot axes (Sv left, Gy right). Nothing sums them (§6.2 LOCKED, #1).
  const sep = await page.evaluate((sel) => {
    const app = window.__APP__;
    const el = document.querySelector(sel);
    return {
      gUnit: app.gammaDoseSeries?.si_unit,
      bUnit: app.betaDoseSeries?.si_unit,
      yTitle: el.layout?.yaxis?.title?.text ?? "",
      y2Title: el.layout?.yaxis2?.title?.text ?? "",
    };
  }, DPLOT);
  record(
    "γ(Sv) vs β(Gy, Hp(0.07)): separate series + separate axes, never summed (§6.2)",
    sep.gUnit === "Sv" &&
      sep.bUnit === "Gy" &&
      sep.yTitle.includes("Sv") &&
      sep.y2Title.includes("Gy"),
    `γ.si_unit=${sep.gUnit}, β.si_unit=${sep.bUnit}, yaxis="${sep.yTitle}", yaxis2="${sep.y2Title}"`,
  );

  // 4) Neutron grayed out for a user inventory (no `source` key — §6.3 gate).
  const neutron = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    return { grayed: el.classList.contains("grayed"), text: el.innerText };
  }, NEUTRON);
  record(
    "neutron grayed for a user inventory (prebuilt sources only, §6.3)",
    neutron.grayed && /N\/A/.test(neutron.text) && /prebuilt/i.test(neutron.text),
    `grayed=${neutron.grayed}, text=${JSON.stringify(neutron.text.replace(/\s+/g, " ").trim())}`,
  );

  // 5) Effective + AP geometry (§13 #3): the dropdown appears defaulting to AP, the
  //    dose recomputes to a DIFFERENT value, and it stays a pure evaluate (registry 1).
  const h10Rate = await page.evaluate(
    (sel) => parseFloat(document.querySelector(sel).getAttribute("data-rate-si")),
    GAMMA,
  );
  await page.click('[data-testid="dose-quantity-effective"]');
  await page.waitForSelector('[data-testid="dose-geometry"]');
  await page.waitForFunction(
    "window.__APP__.doseQuantity === 'effective' && window.__APP__.gammaDoseSeries",
    null,
    { timeout: 30_000 },
  );
  const eff = await page.evaluate((sel) => {
    const s = window.__BRIDGE__.registry_size();
    return {
      geom: document.querySelector('[data-testid="dose-geometry"]').value,
      rate: parseFloat(document.querySelector(sel).getAttribute("data-rate-si")),
      handle: window.__APP__.handle,
      size: s.ok ? s.size : -1,
    };
  }, GAMMA);
  record(
    "effective + AP geometry (§13 #3): dropdown=AP, recomputes, still pure evaluate",
    eff.geom === "AP" &&
      eff.rate !== h10Rate &&
      eff.rate > 0 &&
      eff.size === 1,
    `geometry=${eff.geom}, effRate=${eff.rate.toExponential(3)} ≠ h10Rate=${h10Rate.toExponential(3)}, size=${eff.size}`,
  );
  await page.click('[data-testid="dose-quantity-ambient_H10"]'); // restore

  // 6) Accumulated dose INTEGRATES, never rate×time (§11). Short-lived Tc-99m over one
  //    half-life: ∫₀^t½ A₀e^(-λt)dt = 0.721·A₀·t½, so accumulated/(rate@cursor·t½) ≈
  //    0.72 — strictly < 1 (rate×time would give exactly 1).
  const integ = await page.evaluate(async () => {
    const app = window.__APP__;
    await app.clear();
    await app.addEntry("Tc-99m", 1.0e9, "Bq");
    app.setCursorOffsetS(0); // clamp to range lo → ~full activity at the window start
    const tHalf = app.solveMeta.half_lives_s["Tc-99m"];
    app.setExposureS(tHalf); // exposure window = one half-life
    const rate = app.gammaRateAtCursor; // Sv/s at the window start
    const acc = app.gammaAccumulated; // {value Sv, truncated}
    return {
      tHalf,
      truncated: acc.truncated,
      ratio: acc.value / (rate * tHalf), // ∫rate dt ÷ (rate×t½)
      accum: acc.value,
    };
  });
  record(
    "accumulated dose INTEGRATES (∫rate dt), not rate×time (§11): ratio≈0.72 over one t½",
    !integ.truncated && integ.accum > 0 && integ.ratio > 0.5 && integ.ratio < 0.85,
    `ratio=${integ.ratio.toFixed(3)} (rate×time would be 1.000), truncated=${integ.truncated}, t½=${integ.tHalf.toFixed(1)} s`,
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
  let m6c = { ok: false, checks: [] };
  let m6d = { ok: false, checks: [] };
  let m6f = { ok: false, checks: [] };
  if (m6aOk) {
    m6b = await runM6b(page);
    if (m6b.ok) {
      m6c = await runM6c(page);
      if (m6c.ok) {
        m6d = await runM6d(page);
        if (m6d.ok) {
          m6f = await runM6f(page);
        } else {
          console.log("[gate] skipping M6f — M6d checks failed");
        }
      } else {
        console.log("[gate] skipping M6d/M6f — M6c checks failed");
      }
    } else {
      console.log("[gate] skipping M6c/M6d/M6f — M6b checks failed");
    }
  } else {
    console.log("[gate] skipping M6b/M6c/M6d/M6f — boot self-check failed");
  }

  console.log("\n===== M6b inventory panel =====");
  for (const c of m6b.checks) {
    console.log(`  ${c.pass ? "✓" : "✗"} ${c.name} — ${c.detail}`);
  }

  console.log("\n===== M6c overlay curves =====");
  for (const c of m6c.checks) {
    console.log(`  ${c.pass ? "✓" : "✗"} ${c.name} — ${c.detail}`);
  }

  console.log("\n===== M6d time control =====");
  for (const c of m6d.checks) {
    console.log(`  ${c.pass ? "✓" : "✗"} ${c.name} — ${c.detail}`);
  }

  console.log("\n===== M6f dose calculator =====");
  for (const c of m6f.checks) {
    console.log(`  ${c.pass ? "✓" : "✗"} ${c.name} — ${c.detail}`);
  }

  exitCode = m6aOk && m6b.ok && m6c.ok && m6d.ok && m6f.ok ? 0 : 1;
  console.log(
    exitCode === 0
      ? "\n✅ M6f PASS (real browser): boot + inventory + curves + time control + dose calculator"
      : "\n❌ M6f FAIL (real browser)",
  );
} catch (err) {
  console.error("Driver error:", err);
  exitCode = 1;
} finally {
  if (browser) await browser.close();
  if (server) await server.close();
  process.exit(exitCode);
}
