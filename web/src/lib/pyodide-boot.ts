// Boot the Radiographer physics core in the browser (M6a).
//
// Sequence: inject the Pyodide CDN runtime → micropip-install radioactivedecay →
// fetch ONE combined archive (engine code + runtime data) → extract it into the
// Pyodide FS at "/" with Python's stdlib zipfile → assert the WHOLE data tree
// mounted (the packaging canary) → import engine.bridge → hand back a typed
// BridgeClient.
//
// Decisions (see docs/plans/M6a-bootstrap.md): combined archive extracted to "/";
// zipfile (not pyodide.unpackArchive) for full control + loud errors; CDN-injected
// Pyodide (the path M1 proved) rather than an npm import.

import { BridgeClient } from "./bridge";

/** Number of bundled emission files; pinned natively (data/emissions/*.json). */
export const EXPECTED_NUCLIDE_COUNT = 1252;

const PYODIDE_VERSIONS = ["314.0.0", "0.29.4"];
const cdnFor = (v: string) => `https://cdn.jsdelivr.net/pyodide/v${v}/full/`;
// Resolve against Vite's BASE_URL so the fetch works under base:"./" (built +
// preview) and under any deploy sub-path, not just an absolute site root.
const ARCHIVE_URL = `${import.meta.env.BASE_URL}radiographer-runtime.zip`;

export type BootStage =
  | "pyodide"
  | "micropip"
  | "archive"
  | "extract"
  | "engine"
  | "ready";

export interface BootProgress {
  stage: BootStage;
  detail?: string;
}

export type ProgressFn = (p: BootProgress) => void;

function injectScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = src;
    tag.onload = () => resolve();
    tag.onerror = () => reject(new Error(`failed to load ${src}`));
    document.head.appendChild(tag);
  });
}

/** Load the Pyodide runtime, trying each known-good version in turn. */
async function loadPyodideRuntime(onProgress: ProgressFn): Promise<PyodideInterface> {
  let lastErr: unknown;
  for (const v of PYODIDE_VERSIONS) {
    try {
      onProgress({ stage: "pyodide", detail: `loading Pyodide ${v}…` });
      await injectScript(cdnFor(v) + "pyodide.js");
      return await loadPyodide({ indexURL: cdnFor(v) });
    } catch (err) {
      lastErr = err;
      // Try the next pinned version (CDN hiccup or version pulled).
    }
  }
  throw new Error(
    `could not load Pyodide from the CDN (tried ${PYODIDE_VERSIONS.join(", ")}): ${String(lastErr)}`,
  );
}

/**
 * Boot the engine and return a typed bridge client. Throws loudly on any failure
 * (no fabricated fallback) — the caller surfaces it as a visible error banner.
 */
export async function boot(onProgress: ProgressFn = () => {}): Promise<BridgeClient> {
  const pyodide = await loadPyodideRuntime(onProgress);

  onProgress({ stage: "micropip", detail: "installing radioactivedecay…" });
  await pyodide.loadPackage("micropip");
  const micropip = pyodide.pyimport("micropip");
  await (micropip.install as (n: string) => Promise<void>)("radioactivedecay");

  onProgress({ stage: "archive", detail: "downloading engine + datasets…" });
  const resp = await fetch(ARCHIVE_URL);
  if (!resp.ok) {
    throw new Error(
      `runtime archive ${ARCHIVE_URL} not found (HTTP ${resp.status}). ` +
        `Build it first: \`npm run build:archive\` (from web/).`,
    );
  }
  const bytes = new Uint8Array(await resp.arrayBuffer());

  onProgress({ stage: "extract", detail: `unpacking ${(bytes.length / 1e6).toFixed(1)} MB…` });
  pyodide.FS.writeFile("/tmp/runtime.zip", bytes);

  // Extract to "/" (→ /engine/*.py + /data/<dir>/*.json), wire sys.path, then the
  // PACKAGING CANARY: prove the full tree mounted, not just the few files a 3-nuclide
  // benchmark would touch. A bad (e.g. backslash) arcname yields a near-empty glob —
  // caught here, loudly, before any UI is built on a corrupt mount.
  await pyodide.runPythonAsync(`
import sys, zipfile
with zipfile.ZipFile("/tmp/runtime.zip") as zf:
    zf.extractall("/")
if "/" not in sys.path:
    sys.path.insert(0, "/")
from engine.emissions import available_nuclides
_n = len(available_nuclides())
if _n != ${EXPECTED_NUCLIDE_COUNT}:
    raise RuntimeError(
        f"packaging canary failed: available_nuclides()={_n}, expected ${EXPECTED_NUCLIDE_COUNT}. "
        "The bundled data tree did not mount cleanly (archive arcnames or extract path)."
    )
`);

  onProgress({ stage: "engine", detail: "importing engine.bridge…" });
  await pyodide.runPythonAsync("import engine.bridge");
  const mod = pyodide.pyimport("engine.bridge") as Record<string, (...a: string[]) => string>;

  onProgress({ stage: "ready" });
  return new BridgeClient(mod);
}
