<script lang="ts">
  import { onMount } from "svelte";
  import { boot, type BootProgress } from "./lib/pyodide-boot";
  import { runSelfCheck, type SelfCheckReport } from "./lib/selfcheck";

  type Phase = "booting" | "checking" | "done" | "error";

  let phase = $state<Phase>("booting");
  let progress = $state<string[]>([]);
  let report = $state<SelfCheckReport | null>(null);
  let errorMsg = $state<string>("");
  let errorStack = $state<string>("");

  function onProgress(p: BootProgress) {
    progress = [...progress, p.detail ? `${p.stage}: ${p.detail}` : p.stage];
  }

  onMount(async () => {
    try {
      const client = await boot(onProgress);
      phase = "checking";
      onProgress({ stage: "ready", detail: "running self-check…" });
      const r = runSelfCheck(client);
      report = r;
      phase = "done";
      window.__M6A_RESULT__ = { ok: r.ok, checks: r.checks };
    } catch (err) {
      phase = "error";
      const e = err as Error;
      errorMsg = e?.message ?? String(err);
      errorStack = e?.stack ?? "";
      window.__M6A_RESULT__ = { ok: false, error: errorMsg, stack: errorStack };
    } finally {
      window.__M6A_DONE__ = true;
    }
  });

  const bannerClass = $derived(
    phase === "error" || (phase === "done" && report && !report.ok)
      ? "fail"
      : phase === "done"
        ? "pass"
        : "pending",
  );

  const bannerText = $derived(
    phase === "error"
      ? "❌ Boot failed — see the error below."
      : phase === "done"
        ? report && report.ok
          ? "✅ M6a PASS — engine + full dataset boot in the browser; benchmarks round-trip."
          : "❌ M6a FAIL — see failing checks below."
        : "⏳ Booting Pyodide + engine + datasets (first load pulls the WASM stack + ~tens of MB)…",
  );
</script>

<main>
  <h1>Radiographer <span class="muted">— M6a bootstrap</span></h1>
  <p class="muted">
    Fully client-side: Pyodide (WASM) runs the Python physics engine, the bundled
    ICRP-107 / dose datasets are unpacked into the in-browser filesystem, and every
    number below is computed on-device. <strong>Not for safety decisions</strong> (§11).
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

  {#if report}
    <section>
      <h2>Self-check ({report.checks.filter((c) => c.pass).length}/{report.checks.length} passed)</h2>
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
