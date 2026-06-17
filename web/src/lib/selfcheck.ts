// M6a kill-early gate: run the validated physics benchmarks THROUGH the typed
// bridge client (the real app path), not raw Python. Every number here is pulled
// from a passing Python test (tests/test_bridge.py, tests/test_dose_gamma.py) —
// nothing invented. If this passes in a real headless browser, the Pyodide +
// engine + full-dataset foundation is viable and M6 can build on it.

import type { BridgeClient, Handle, SolveResponse } from "./bridge";

export interface CheckResult {
  name: string;
  pass: boolean;
  detail: string;
}

export interface SelfCheckReport {
  ok: boolean;
  checks: CheckResult[];
}

function approxRel(got: number, want: number, rel: number): boolean {
  return Math.abs(got - want) <= Math.abs(want) * rel;
}

/** Narrowing helper: a solve must succeed and yield a usable handle. */
function expectSolved(res: SolveResponse, label: string): Handle {
  if (!res.ok) {
    throw new Error(`${label}: solve failed — ${res.error.type}: ${res.error.message}`);
  }
  return res.handle;
}

export function runSelfCheck(client: BridgeClient): SelfCheckReport {
  const checks: CheckResult[] = [];
  const record = (name: string, pass: boolean, detail: string) =>
    checks.push({ name, pass, detail });

  // 1 + 2) Co-60 air-kerma @ 1 m, and the H*(10)/Kₐ ratio (exercises emissions +
  // attenuation μ_en/ρ AND the separate pSv·cm² conversion path) — one solve, two doses.
  try {
    const handle = expectSolved(
      client.solve({ nuclides: { "Co-60": 1.0e9 }, unit: "Bq" }),
      "Co-60",
    );
    try {
      const ka = client.dose(handle, { times_s: [0.0], quantity: "air_kerma", distance_m: 1.0 });
      if (!ka.ok) throw new Error(`air_kerma dose: ${ka.error.type}: ${ka.error.message}`);
      const mGyh = ka.rate_si[0] * 1000.0 * 3600.0;
      record(
        "Co-60 air-kerma @1m ≈ 0.308 mGy·m²·GBq⁻¹·h⁻¹",
        approxRel(mGyh, 0.308, 0.03) &&
          ka.si_unit === "Gy" &&
          ka.scoring_floor_MeV === 0.01 &&
          ka.warnings.length > 0,
        `${mGyh.toFixed(4)} mGy/h, unit=${ka.si_unit}, floor=${ka.scoring_floor_MeV}, ` +
          `${ka.warnings.length} warning(s)`,
      );

      const h10 = client.dose(handle, {
        times_s: [0.0],
        quantity: "ambient_H10",
        distance_m: 1.0,
      });
      if (!h10.ok) throw new Error(`H*(10) dose: ${h10.error.type}: ${h10.error.message}`);
      const ratio = h10.rate_si[0] / ka.rate_si[0];
      record(
        "Co-60 H*(10)/Kₐ ratio ∈ (1.05, 1.30) [conversion tables]",
        ratio > 1.05 && ratio < 1.3 && h10.si_unit === "Sv",
        `ratio=${ratio.toFixed(4)}, H*(10) unit=${h10.si_unit}`,
      );
    } finally {
      client.release(handle);
    }
  } catch (err) {
    record("Co-60 dose benchmarks", false, String(err));
  }

  // 3) Cs-137 secular equilibrium A(Ba-137m)/A(Cs-137) ≈ 0.94399 @ 1 d; no HP needed.
  try {
    const solved = client.solve({ nuclides: { "Cs-137": 1.0 }, unit: "Bq" });
    const handle = expectSolved(solved, "Cs-137");
    try {
      const hpFlag = solved.ok ? solved.hp_recommended : true;
      const ev = client.evaluate(handle, { times_s: [86400.0], axis: "activity", unit: "Bq" });
      if (!ev.ok) throw new Error(`evaluate: ${ev.error.type}: ${ev.error.message}`);
      const ratio = ev.series["Ba-137m"][0] / ev.series["Cs-137"][0];
      record(
        "Cs-137 secular equilibrium ≈ 0.94399 @ 1 d",
        approxRel(ratio, 0.94399, 1e-3 / 0.94399) && hpFlag === false,
        `ratio=${ratio.toFixed(6)}, hp_recommended=${hpFlag}`,
      );
    } finally {
      client.release(handle);
    }
  } catch (err) {
    record("Cs-137 secular equilibrium", false, String(err));
  }

  // 4) HP path in WASM (M1 open risk): U-238 with precision:"hp" must build
  // rd.InventoryHP (→ sympy) under WASM and evaluate to finite, non-negative values.
  try {
    const solved = client.solve({ nuclides: { "U-238": 1.0 }, unit: "Bq", precision: "hp" });
    const handle = expectSolved(solved, "U-238 (hp)");
    try {
      const [lo, hi] = solved.ok ? solved.time_range_s : [1, 1e17];
      const grid = [0.0, lo, Math.sqrt(lo * hi), hi];
      const ev = client.evaluate(handle, { times_s: grid, axis: "activity", unit: "Bq" });
      if (!ev.ok) throw new Error(`evaluate: ${ev.error.type}: ${ev.error.message}`);
      const allFinite = Object.values(ev.series).every((col) =>
        col.every((v) => Number.isFinite(v) && v >= 0),
      );
      record(
        "HP (arbitrary-precision) path runs in WASM [U-238]",
        (solved.ok ? solved.hp_recommended : false) === true && allFinite,
        `hp_recommended=${solved.ok && solved.hp_recommended}, ${ev.nuclides.length} nuclides, all finite=${allFinite}`,
      );
    } finally {
      client.release(handle);
    }
  } catch (err) {
    record("HP path in WASM", false, `${String(err)} (fix: micropip.install(["radioactivedecay","sympy"]))`);
  }

  // 5) A bad nuclide is a LOUD structured error across the bridge (no silent zero).
  try {
    const bad = client.solve({ nuclides: { "Zz-000": 1.0 }, unit: "Bq" });
    record(
      "Unknown nuclide → loud structured error",
      bad.ok === false && bad.error.type === "EngineError",
      bad.ok ? "unexpectedly ok" : `${bad.error.type}: ${bad.error.message}`,
    );
  } catch (err) {
    record("Unknown nuclide error", false, String(err));
  }

  return { ok: checks.every((c) => c.pass), checks };
}
