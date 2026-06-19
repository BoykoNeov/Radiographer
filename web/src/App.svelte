<script lang="ts">
  import { onMount } from "svelte";
  import { boot, type BootProgress } from "./lib/pyodide-boot";
  import { runSelfCheck, type SelfCheckReport } from "./lib/selfcheck";
  import { appState } from "./lib/state.svelte";
  import Inventory from "./lib/Inventory.svelte";
  import Curves from "./lib/Curves.svelte";
  import TimeControl from "./lib/TimeControl.svelte";
  import Chain from "./lib/Chain.svelte";
  import Dose from "./lib/Dose.svelte";
  import Shield from "./lib/Shield.svelte";

  type Phase = "booting" | "ready" | "error";

  let phase = $state<Phase>("booting");
  let progress = $state<string[]>([]);
  let report = $state<SelfCheckReport | null>(null);
  let errorMsg = $state<string>("");
  let errorStack = $state<string>("");

  // The kill-early boot self-check (M6a) is heavy (it runs the multi-second U-238 HP
  // path). It is no longer the app's job on every load — only the headless gate needs
  // it — so it runs only under ?selfcheck=1 (set by drive_browser.mjs). Production boot
  // stays fast.
  const wantSelfCheck =
    typeof location !== "undefined" && new URLSearchParams(location.search).has("selfcheck");

  function onProgress(p: BootProgress) {
    progress = [...progress, p.detail ? `${p.stage}: ${p.detail}` : p.stage];
  }

  onMount(async () => {
    try {
      const client = await boot(onProgress);
      appState.setClient(client);
      window.__APP__ = appState;
      window.__BRIDGE__ = client; // gate: assert released handles are dead + no leak
      phase = "ready";

      if (wantSelfCheck) {
        onProgress({ stage: "ready", detail: "running boot self-check…" });
        const r = runSelfCheck(client);
        report = r;
        window.__M6A_RESULT__ = { ok: r.ok, checks: r.checks };
      }
    } catch (err) {
      phase = "error";
      const e = err as Error;
      errorMsg = e?.message ?? String(err);
      errorStack = e?.stack ?? "";
      window.__M6A_RESULT__ = { ok: false, error: errorMsg, stack: errorStack };
    } finally {
      window.__BOOT_DONE__ = true;
      window.__M6A_DONE__ = true; // back-compat with the existing gate name
    }
  });

  const bannerClass = $derived(phase === "error" ? "fail" : phase === "ready" ? "pass" : "pending");
  const bannerText = $derived(
    phase === "error"
      ? "❌ Boot failed — see the error below."
      : phase === "ready"
        ? "✅ Engine + full dataset booted in the browser — on-device physics ready."
        : "⏳ Booting Pyodide + engine + datasets (first load pulls the WASM stack + ~tens of MB)…",
  );
</script>

<main>
  <h1>Radiographer <span class="muted">— decay & dose (M6g)</span></h1>
  <p class="muted">
    Fully client-side: Pyodide (WASM) runs the Python physics engine, the bundled
    ICRP-107 / dose datasets are unpacked into the in-browser filesystem, and every
    number is computed on-device. <strong>Not for safety decisions</strong> (§11).
  </p>

  <div class="banner {bannerClass}">{bannerText}</div>

  {#if phase === "error"}
    <section class="error">
      <h2>Error</h2>
      <pre>{errorMsg}</pre>
      {#if errorStack}
        <details><summary>Stack trace</summary><pre>{errorStack}</pre></details>
      {/if}
    </section>
  {/if}

  {#if phase === "ready"}
    <Inventory />
    <Curves />
    <TimeControl />
    <Chain />
    <Dose />
    <Shield />
  {/if}

  {#if report}
    <section>
      <h2>Boot self-check ({report.checks.filter((c) => c.pass).length}/{report.checks.length} passed)</h2>
      <table>
        <tbody>
          {#each report.checks as c (c.name)}
            <tr class={c.pass ? "ok" : "bad"}>
              <td>{c.pass ? "✓" : "✗"}</td>
              <td>{c.name}</td>
              <td class="muted mono">{c.detail}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>
  {/if}

  <section>
    <h2>Boot log</h2>
    <pre class="log">{progress.join("\n") || "…"}</pre>
  </section>
</main>

<style>
  :global(:root) {
    color-scheme: light dark;
  }
  :global(body) {
    margin: 0;
  }
  main {
    font: 14px/1.5 system-ui, sans-serif;
    margin: 2rem auto;
    max-width: 72rem;
    padding: 0 1rem;
  }
  h1 {
    font-size: 1.4rem;
  }
  h2 {
    font-size: 1.05rem;
    margin-top: 1.5rem;
  }
  .muted {
    opacity: 0.7;
  }
  .mono {
    font-family: ui-monospace, monospace;
    font-size: 12px;
  }
  .banner {
    padding: 0.75rem 1rem;
    border-radius: 0.5rem;
    font-weight: 600;
    font-size: 1.05rem;
  }
  .pending {
    background: #fff3cd;
    color: #664d03;
  }
  .pass {
    background: #d1e7dd;
    color: #0f5132;
  }
  .fail {
    background: #f8d7da;
    color: #842029;
  }
  table {
    border-collapse: collapse;
    width: 100%;
  }
  td {
    border: 1px solid #8884;
    padding: 0.3rem 0.6rem;
    text-align: left;
    vertical-align: top;
  }
  tr.ok td:first-child {
    color: #0f5132;
    font-weight: 700;
  }
  tr.bad td:first-child {
    color: #842029;
    font-weight: 700;
  }
  pre,
  .log {
    white-space: pre-wrap;
    font-family: ui-monospace, monospace;
    font-size: 12px;
    background: #00000010;
    padding: 0.75rem;
    border-radius: 0.5rem;
    overflow-x: auto;
  }
  section.error pre {
    background: #f8d7da66;
  }
</style>
