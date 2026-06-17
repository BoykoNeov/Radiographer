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
    // Headless-driver contract (set by App.svelte once the M6a gate resolves).
    __M6A_DONE__?: boolean;
    __M6A_RESULT__?: unknown;
  }
}

export {};
