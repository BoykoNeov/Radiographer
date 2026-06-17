<script lang="ts">
  // Decay-chain DAG (M6-ui M6e, §8/§9): the Cytoscape view of the loaded inventory's
  // descendant closure. A PURE renderer — it reads the store's `chainDag` (topology,
  // fetched once per solve) and `activityAtCursor` (the live encoding) and never
  // touches the BridgeClient. Two switchable layouts: **dagre** (compact, Sugiyama)
  // and the **(N, Z) chart-of-nuclides preset** (physically meaningful) — §8.
  //
  // Live encoding (§9): node SIZE + OPACITY track the slider-time ACTIVITY, so
  // scrubbing shows the parent fade and a daughter grow in (secular/transient
  // equilibrium becomes visible on the diagram). The graph is built ONCE per topology
  // change; a cursor move is a cheap `cy.batch()` data update (size/opacity only),
  // NEVER a rebuild or re-layout — the §3 "relayout-not-react" payoff, exactly like
  // the M6d curve cursor. Colors are the shared per-species palette (#4); the SF
  // pseudo-sink is the honest "fission products" terminal (not an activity quantity).
  //
  // Per-emission ENERGIES are deliberately not shown here — `build_dag` carries decay
  // topology only; the per-line photon/beta energies live in the dose per-line table
  // (M6f-2). The tooltip shows half-life, Z/A/N, decay modes, and live activity.
  import cytoscape from "cytoscape";
  import dagre from "cytoscape-dagre";
  import { onDestroy, untrack } from "svelte";
  import { appState } from "./state.svelte";
  import type { ChainNode } from "./bridge";

  cytoscape.use(dagre); // register the dagre layout once (else `layout:"dagre"` throws)

  const SF_ID = "SF";
  const SF_COLOR = "#9e9e9e";

  // -- live-encoding scale (node size/opacity ← activity) ----------------------
  // Normalized against the FIXED global activity peak over the whole series (not the
  // per-frame peak), so absolute decay reads as an overall fade and in-growth as a
  // daughter swelling — the literal §9 "parent fade, daughter grow in". A node ENC_DECADES
  // below the global peak (or zero-activity: stable end-products, the SF sink) sits at
  // the faded floor — an honest "negligible here", never hidden (advisor #4).
  const SIZE_MIN = 22;
  const SIZE_MAX = 64;
  const OP_MIN = 0.4;
  const OP_MAX = 1.0;
  const ENC_DECADES = 6;
  const SIZE_NEUTRAL = 44; // topology-only fallback when there is no activity (all-stable)
  const NZ_SPACING = 70; // px per (N or Z) unit in the chart-of-nuclides preset

  type LayoutMode = "dagre" | "chart";
  let layoutMode = $state<LayoutMode>("dagre");

  let containerEl = $state<HTMLDivElement | null>(null);
  let cy: cytoscape.Core | null = null;
  let presetPositions: Record<string, cytoscape.Position> = {};
  let hovered = $state<string | null>(null); // node id under the pointer (tooltip)

  const hasDag = $derived((appState.chainDag?.nodes.length ?? 0) > 0);

  /** The fixed global activity peak (Bq) over the whole series — the encoding's top. */
  const activityPeak = $derived.by(() => {
    const s = appState.chainActivity;
    if (!s) return 0;
    let peak = 0;
    for (const n of s.nuclides) {
      for (const v of s.series[n] ?? []) if (Number.isFinite(v) && v > peak) peak = v;
    }
    return peak;
  });

  /** Map an activity (Bq) to {size, opacity}; faded floor for ≤0 / below ENC_DECADES. */
  function encode(activity: number, peak: number): { size: number; op: number } {
    if (!(peak > 0) || !(activity > 0)) return { size: SIZE_MIN, op: OP_MIN };
    const floor = peak / 10 ** ENC_DECADES;
    if (activity <= floor) return { size: SIZE_MIN, op: OP_MIN };
    const frac = (Math.log10(activity) - Math.log10(floor)) / (Math.log10(peak) - Math.log10(floor));
    const f = Math.min(1, Math.max(0, frac));
    return { size: SIZE_MIN + f * (SIZE_MAX - SIZE_MIN), op: OP_MIN + f * (OP_MAX - OP_MIN) };
  }

  /** (N, Z) chart-of-nuclides position: x = N, y = −Z (Z up). Metastable isomers share
   *  (N, Z) with their ground state, so nudge them diagonally to keep both visible. */
  function nzPosition(n: ChainNode): cytoscape.Position | null {
    if (n.Z == null || n.N == null) return null; // the SF sink — placed separately
    const rank = n.state === "" ? 0 : n.state === "n" ? 2 : 1; // m/n isomer offset
    return { x: (n.N + rank * 0.33) * NZ_SPACING, y: -(n.Z + rank * 0.33) * NZ_SPACING };
  }

  /** Build the (N, Z) preset position map, placing the SF sink below-left of the chain. */
  function buildPresetPositions(nodes: ChainNode[]): Record<string, cytoscape.Position> {
    const pos: Record<string, cytoscape.Position> = {};
    let minZ = Infinity;
    let minN = Infinity;
    for (const n of nodes) {
      const p = nzPosition(n);
      if (p) {
        pos[n.id] = p;
        if (n.Z != null) minZ = Math.min(minZ, n.Z);
        if (n.N != null) minN = Math.min(minN, n.N);
      }
    }
    if (pos[SF_ID] === undefined && nodes.some((n) => n.id === SF_ID)) {
      // Below the lowest-Z member (fission products terminate the branch).
      pos[SF_ID] = {
        x: (Number.isFinite(minN) ? minN : 0) * NZ_SPACING,
        y: -((Number.isFinite(minZ) ? minZ : 0) - 2) * NZ_SPACING,
      };
    }
    return pos;
  }

  function elements(): cytoscape.ElementDefinition[] {
    const dag = appState.chainDag;
    if (!dag) return [];
    const colors = appState.colors;
    const nodes: cytoscape.ElementDefinition[] = dag.nodes.map((n) => {
      const isSink = n.id === SF_ID;
      return {
        data: {
          id: n.id,
          label: n.label ?? n.id,
          color: isSink ? SF_COLOR : (colors[n.id] ?? "#888"),
          // raw fields for the hover tooltip
          Z: n.Z,
          A: n.A,
          N: n.N,
          hl: n.half_life_readable,
          stable: n.stable,
          modes: n.decay_modes.join(", "),
          sink: isSink,
        },
        // NOTE: deliberately no initial `position` — cytoscape uses an element's
        // position object BY REFERENCE and the dagre layout mutates it in place, which
        // would clobber `presetPositions`. The (N, Z) coords are supplied only via the
        // chart layout's `positions` map (fresh copies, see `layoutOptions`).
      };
    });
    const edges: cytoscape.ElementDefinition[] = dag.edges.map((e, i) => ({
      data: {
        id: `e${i}:${e.source}-${e.mode}-${e.target}`,
        source: e.source,
        target: e.target,
        label: `${e.mode} ${fmtPct(e.branching)}`,
      },
    }));
    return [...nodes, ...edges];
  }

  function fmtPct(bf: number): string {
    const p = bf * 100;
    return `${p >= 1 ? p.toFixed(1) : p.toPrecision(2)}%`;
  }

  // Base stylesheet is STATIC (color/label/shape). Size + opacity are the LIVE encoding
  // and are set imperatively per-node via `node.style()` in `applyEncoding` (a cheap
  // batched bypass) — keeps the reactive path explicit and sidesteps the numeric-mapper
  // type. The `node[?sink]` selector styles the SF terminal (left untouched by the encoder).
  const STYLE: cytoscape.StylesheetStyle[] = [
    {
      selector: "node",
      style: {
        "background-color": "data(color)",
        label: "data(label)",
        width: SIZE_NEUTRAL,
        height: SIZE_NEUTRAL,
        opacity: OP_MAX,
        "font-size": 11,
        "text-valign": "center",
        "text-halign": "center",
        color: "#fff",
        "text-outline-color": "#000",
        "text-outline-width": 1.5,
        "border-width": 1,
        "border-color": "#999",
      },
    },
    {
      selector: 'node[?sink]',
      style: { shape: "round-rectangle", "font-size": 10, width: 90, height: 30, opacity: 0.7 },
    },
    {
      selector: "edge",
      style: {
        width: 1.5,
        "line-color": "#9aa0a6",
        "target-arrow-color": "#9aa0a6",
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        label: "data(label)",
        "font-size": 9,
        color: "#888",
        "text-background-color": "#7f7f7f",
        "text-background-opacity": 0.18,
        "text-background-padding": "1px",
      },
    },
  ];

  function layoutOptions(mode: LayoutMode): cytoscape.LayoutOptions {
    if (mode === "chart") {
      // Fresh COPIES of every (N, Z) coord — cytoscape uses position objects by
      // reference and a later layout would otherwise mutate our canonical map.
      const positions: Record<string, cytoscape.Position> = {};
      for (const id of Object.keys(presetPositions)) positions[id] = { ...presetPositions[id] };
      return { name: "preset", positions, fit: true, padding: 30 };
    }
    // dagre: top→bottom layered DAG (parents above daughters), re-convergence handled.
    return {
      name: "dagre",
      rankDir: "TB",
      nodeSep: 30,
      rankSep: 50,
      fit: true,
      padding: 30,
    } as cytoscape.LayoutOptions;
  }

  /** Apply the live activity encoding (size/opacity) to every node — a cheap batched
   *  data update, never a rebuild or re-layout (§3). SF/missing nodes stay neutral. */
  function applyEncoding(): void {
    if (!cy) return;
    const activity = appState.activityAtCursor; // {nuclide: Bq} | null (all-stable)
    const peak = activityPeak;
    cy.batch(() => {
      cy!.nodes().forEach((node) => {
        const id = node.id();
        if (id === SF_ID) return; // the sink is not an activity quantity — leave neutral
        if (!activity) {
          node.style({ width: SIZE_NEUTRAL, height: SIZE_NEUTRAL, opacity: 0.9 }); // topology-only
          return;
        }
        const { size, op } = encode(activity[id] ?? 0, peak);
        node.style({ width: size, height: size, opacity: op });
      });
    });
  }

  function destroyCy(): void {
    if (cy) {
      cy.destroy();
      cy = null;
    }
    if (typeof window !== "undefined") window.__CY__ = null;
  }

  // Build the graph ONCE per topology change (chainDag) or palette change (colors).
  // The cursor/activity is read untracked here for the initial frame; subsequent
  // cursor moves ride the cheap encoding effect below. layoutMode is read untracked
  // so a layout toggle does not rebuild (its own effect re-runs the layout).
  $effect(() => {
    const dag = appState.chainDag;
    void appState.colors; // rebuild on palette reassignment (re-solve)
    const el = containerEl;
    if (!el) return;
    if (!dag || dag.nodes.length === 0) {
      destroyCy();
      return;
    }
    untrack(() => {
      destroyCy();
      presetPositions = buildPresetPositions(dag.nodes);
      cy = cytoscape({
        container: el,
        elements: elements(),
        style: STYLE,
        layout: layoutOptions(layoutMode),
      });
      cy.on("mouseover", "node", (ev) => (hovered = ev.target.id()));
      cy.on("mouseout", "node", () => (hovered = null));
      cy.on("tap", "node", (ev) => (hovered = ev.target.id()));
      applyEncoding(); // initial frame at the current cursor
      if (typeof window !== "undefined") window.__CY__ = cy; // gate hook (canvas → no DOM)
    });
  });

  // Live encoding: a cursor move (or source-age change) re-derives activityAtCursor;
  // restyle the nodes cheaply. NO rebuild, NO re-layout, NO bridge call (§3).
  $effect(() => {
    void appState.activityAtCursor; // the tracked dep
    void activityPeak;
    if (cy) applyEncoding();
  });

  // Layout toggle (imperative): re-run the chosen layout on the existing graph
  // (positions only — never a rebuild). Driven directly from the click handler rather
  // than a $effect so there is no effect-ordering ambiguity vs the build effect.
  function setLayout(mode: LayoutMode): void {
    layoutMode = mode;
    if (cy) cy.layout(layoutOptions(mode)).run();
  }

  onDestroy(destroyCy);

  // -- tooltip data for the hovered node --------------------------------------
  const hoverNode = $derived.by(() => {
    const id = hovered;
    if (!id) return null;
    const n = appState.chainDag?.nodes.find((x) => x.id === id);
    if (!n) return null;
    const act = appState.activityAtCursor?.[id];
    return { node: n, activityBq: act ?? null };
  });
</script>

{#if appState.solveMeta}
  <section class="chain" data-testid="chain">
    <header>
      <h2>Decay chain</h2>
      <div class="layout-toggle" role="group" aria-label="Chain layout" data-testid="chain-layout">
        <button
          class:selected={layoutMode === "dagre"}
          aria-pressed={layoutMode === "dagre"}
          data-testid="chain-layout-dagre"
          onclick={() => setLayout("dagre")}
        >
          Dagre
        </button>
        <button
          class:selected={layoutMode === "chart"}
          aria-pressed={layoutMode === "chart"}
          data-testid="chain-layout-chart"
          onclick={() => setLayout("chart")}
        >
          Chart (N, Z)
        </button>
      </div>
    </header>

    {#if appState.chainError}
      <p class="note error" role="alert">⚠ chain failed — {appState.chainError}</p>
    {:else if !hasDag}
      <p class="note muted">Add an isotope above to see its decay chain.</p>
    {/if}

    <!-- The graph container is always present so the $effect can build/destroy it. -->
    <div class="graph" data-testid="chain-graph" class:empty={!hasDag} bind:this={containerEl}></div>

    {#if hasDag}
      <div class="tooltip" data-testid="chain-tooltip">
        {#if hoverNode}
          {#if hoverNode.node.id === "SF"}
            <strong>{hoverNode.node.label}</strong> — honest terminal sink; fission
            products are out of scope (v1 models decay topology only, §6.3).
          {:else}
            <strong>{hoverNode.node.id}</strong>
            <span class="muted">Z={hoverNode.node.Z}, N={hoverNode.node.N}, A={hoverNode.node.A}</span>
            · t½ <strong>{hoverNode.node.half_life_readable}</strong>
            {#if hoverNode.node.decay_modes.length > 0}
              · modes {hoverNode.node.decay_modes.join(", ")}
            {/if}
            · activity now
            <strong>{hoverNode.activityBq == null ? "—" : `${hoverNode.activityBq.toExponential(3)} Bq`}</strong>
          {/if}
        {:else}
          <span class="muted">Hover a node for half-life, decay modes &amp; live activity (at the time cursor).</span>
        {/if}
      </div>
    {/if}

    <p class="hint muted">
      Node size &amp; opacity track each species' <strong>activity at the time cursor</strong>
      (§9) — scrub the slider above to watch the parent fade and daughters grow in; one
      Bateman solve, evaluated many (§3). Edges label the decay mode + branching %; colors
      are the shared per-species palette. <strong>Dagre</strong> is a compact layered DAG;
      <strong>Chart (N, Z)</strong> places each node by neutron/proton number (α steps
      down-left, β⁻ a diagonal step — re-convergence falls out because a shared daughter is
      one coordinate). Per-emission energies appear in the dose per-line table (M6f-2).
    </p>
  </section>
{/if}

<style>
  .chain {
    border: 1px solid #8884;
    border-radius: 0.5rem;
    padding: 1rem;
    margin-top: 1rem;
  }
  header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }
  h2 {
    margin: 0;
    font-size: 1.05rem;
    margin-right: auto;
  }
  .layout-toggle {
    display: inline-flex;
    border: 1px solid #8886;
    border-radius: 0.4rem;
    overflow: hidden;
  }
  .layout-toggle button {
    font: inherit;
    border: none;
    background: transparent;
    padding: 0.3rem 0.7rem;
    cursor: pointer;
    border-left: 1px solid #8886;
  }
  .layout-toggle button:first-child {
    border-left: none;
  }
  .layout-toggle button.selected {
    background: #4e79a7;
    color: #fff;
    font-weight: 600;
  }
  .graph {
    width: 100%;
    height: 460px;
    margin-top: 0.75rem;
    border: 1px solid #8883;
    border-radius: 0.4rem;
    background: #00000008;
  }
  .graph.empty {
    height: 0;
    margin: 0;
    border: none;
  }
  .tooltip {
    margin-top: 0.5rem;
    font-size: 0.85rem;
    min-height: 1.4em;
  }
  .note {
    margin: 0.75rem 0 0;
    font-weight: 600;
  }
  .note.error {
    color: #b3261e;
  }
  .muted {
    opacity: 0.7;
    font-weight: 400;
  }
  .hint {
    margin: 0.6rem 0 0;
    font-size: 0.85rem;
  }
</style>
