/// <reference types="svelte" />
/// <reference types="vite/client" />

// Pyodide is loaded by injecting its CDN <script>, which defines a global
// `loadPyodide`. We type it loosely here (the bridge client wraps the surface we
// actually use); see src/lib/pyodide-boot.ts.
declare global {
  interface PyProxyCallable {
    (...args: unknown[]): unknown;
  }

  interface PyodideInterface {
    runPythonAsync(code: string): Promise<unknown>;
    loadPackage(names: string | string[]): Promise<void>;
    pyimport(name: string): Record<string, PyProxyCallable>;
    FS: {
      writeFile(path: string, data: Uint8Array | string): void;
      mkdirTree(path: string): void;
    };
  }

  function loadPyodide(config: { indexURL: string }): Promise<PyodideInterface>;

  interface Window {
    loadPyodide?: (config: { indexURL: string }) => Promise<PyodideInterface>;
    // Headless-driver contract. Boot always sets __BOOT_DONE__; the M6a boot
    // self-check (run only under ?selfcheck=1) sets __M6A_RESULT__. The M6b gate
    // drives the DOM and reads __APP__ (the live store) for palette + round-trip.
    __BOOT_DONE__?: boolean;
    __M6A_DONE__?: boolean;
    __M6A_RESULT__?: unknown;
    __APP__?: unknown;
    __BRIDGE__?: unknown;
    // M7: the prebuilt source catalog manifest, exposed for the gate to assert it loaded.
    __SOURCES__?: unknown;
    // M6e: the live Cytoscape instance (canvas → no DOM to assert against), exposed
    // for the headless gate to read node/edge data, sizes, and positions.
    __CY__?: unknown;
    // Diagnostic only (gate-js-heap-runaway, HANDOFF_PLAN §13 item 8): a rAF-driven
    // heap + render-count sampler, active only under ?selfcheck=1. Lets the gate
    // diff a passing run's trajectory against a hanging one instead of guessing.
    __PERF__?: {
      renders: { curvesReact: number; cyBuild: number; cyEncode: number };
      frames: Array<{ t: number; heap: number | null; curvesReact: number; cyBuild: number; cyEncode: number }>;
    };
  }
}

export {};
