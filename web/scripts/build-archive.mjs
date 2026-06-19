// Assemble the ONE combined runtime archive the browser fetches at boot:
// engine/*.py + the 5 runtime data dirs, zipped with forward-slash arcnames so
// Python's zipfile.extractall("/") reproduces a real /engine + /data tree (on
// Windows too — see docs/plans/M6a-bootstrap.md decision #4).
//
// Pure Node + fflate (zero-friction `npm install`; fflate guarantees the keys we
// give it become the arcnames verbatim). Excludes data/vendor + data/build (build
// inputs, not runtime). mtime-aware: rebuilds only when a source is newer than the
// zip, unless `--force` is passed.
//
// Run: node scripts/build-archive.mjs [--force]

import { readFileSync, writeFileSync, readdirSync, statSync, mkdirSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { zipSync } from "fflate";

// scripts/ -> web/ -> repo root
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const OUT = path.resolve(ROOT, "web", "public", "radiographer-runtime.zip");

// Runtime data dirs (NOT vendor/build/raw — those are build inputs, ~17 MB).
const DATA_DIRS = ["emissions", "conversion", "attenuation", "buildup", "neutron_sources", "neutron_removal", "spent_fuel", "fallout"];

const force = process.argv.includes("--force");

/** All source files (abs path + POSIX arcname) that go into the archive. */
function collectSources() {
  const out = [];
  // engine/*.py
  const engineDir = path.join(ROOT, "engine");
  for (const f of readdirSync(engineDir)) {
    if (f.endsWith(".py")) {
      out.push({ abs: path.join(engineDir, f), arc: `engine/${f}` });
    }
  }
  // data/<dir>/*.json
  for (const dir of DATA_DIRS) {
    const d = path.join(ROOT, "data", dir);
    if (!existsSync(d)) throw new Error(`missing runtime data dir: ${d}`);
    for (const f of readdirSync(d)) {
      if (f.endsWith(".json")) {
        out.push({ abs: path.join(d, f), arc: `data/${dir}/${f}` });
      }
    }
  }
  return out;
}

function newestMtime(sources) {
  let m = 0;
  for (const s of sources) m = Math.max(m, statSync(s.abs).mtimeMs);
  return m;
}

function main() {
  const sources = collectSources();

  if (!force && existsSync(OUT) && statSync(OUT).mtimeMs >= newestMtime(sources)) {
    console.log(`[build-archive] up to date (${sources.length} files) → ${path.relative(ROOT, OUT)}`);
    return;
  }

  const files = {};
  for (const s of sources) files[s.arc] = readFileSync(s.abs); // arc keys = forward-slash POSIX

  // Sanity: no backslash leaked into an arcname (would break extractall on the FS).
  for (const k of Object.keys(files)) {
    if (k.includes("\\")) throw new Error(`backslash in arcname ${JSON.stringify(k)}`);
  }

  const zipped = zipSync(files, { level: 6 });
  mkdirSync(path.dirname(OUT), { recursive: true });
  writeFileSync(OUT, zipped);

  const rawMB = sources.reduce((a, s) => a + statSync(s.abs).size, 0) / 1e6;
  console.log(
    `[build-archive] ${sources.length} files, ${rawMB.toFixed(1)} MB raw → ` +
      `${(zipped.length / 1e6).toFixed(1)} MB zip → ${path.relative(ROOT, OUT)}`,
  );
}

main();
