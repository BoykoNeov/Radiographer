<script lang="ts">
  // Beam probe (§9 shield builder) — test the SHIELD STACK against an external beam instead of
  // against the loaded inventory: a single photon line ("how well does this stop 60 keV?") or an
  // idealized X-ray tube spectrum ("…a 100 kVp beam?"). Lives inside the Shield panel because
  // that is what it measures: transmission is a property of the layer stack, not of a source.
  //
  // TRANSMISSION ONLY, never an absolute dose rate. An X-ray tube's output (mGy/mAs at 1 m) is
  // a tube-and-geometry calibration that is NOT in `data/` — inventing one would be exactly the
  // fabrication this project refuses. So every number here is a ratio, a thickness, a mean
  // energy, or a relative spectrum shape. The user's own measured unshielded rate × the
  // transmission is the honest way to get an absolute number, and the copy says so.
  //
  // The bridge call is STATELESS (no handle, no solve) and the store makes it a no-op while the
  // probe is closed, so this panel costs nothing until it is opened and can never grow the solve
  // registry (the gate asserts registry==1 across a probe).
  //
  // The load-bearing honesty element is the SCORED BAND: ANS-6.4.3 buildup starts at 15 keV
  // (30 keV for lead), and the engine refuses to substitute B=1 below it (that would under-count
  // dose). So the line input is clamped to the stack's band, and the tube mode reports the
  // dropped incident fraction as a headline number — see engine/beam.py for the full argument.
  import Plotly from "plotly.js-basic-dist-min";
  import { onDestroy } from "svelte";
  import { appState } from "./state.svelte";
  import { MODALITY_COLORS } from "./types";
  import Term from "./Term.svelte";
  import LearnMore from "./LearnMore.svelte";

  let curveEl = $state<HTMLDivElement | null>(null);
  let specEl = $state<HTMLDivElement | null>(null);

  const mode = $derived(appState.beamMode);
  const probe = $derived(appState.beamProbe);
  const line = $derived(probe?.line ?? null);
  const tube = $derived(probe?.tube ?? null);
  const band = $derived(appState.beamBandKeV);
  const presets = $derived(appState.beamLinePresets);
  const stack = $derived(appState.shieldStackLabel);
  const detector = $derived(line?.detector_material ?? null);

  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  const pct = (f: number) => `${(f * 100).toFixed(f < 0.01 ? 2 : 1)}%`;
  const keV = (mev: number | null) => (mev == null ? "—" : `${(mev * 1e3).toFixed(1)} keV`);
  /** Transmission spans ~15 decades, so switch to exponential where a fixed format goes to 0. */
  const frac = (t: number | null) => (t == null ? "—" : t >= 1e-3 ? t.toFixed(4) : t.toExponential(3));
  /** cm → the unit a shielding thickness is actually quoted in at that scale (§12). */
  const thick = (cm: number | null) =>
    cm == null ? "—" : cm < 0.1 ? `${(cm * 10).toFixed(3)} mm` : `${cm.toFixed(3)} cm`;

  function onLineEnergy(e: Event) {
    const el = e.target as HTMLInputElement;
    const v = parseFloat(el.value);
    if (Number.isFinite(v) && v > 0) appState.setBeamLineKeV(v);
    el.value = String(appState.beamLineKeV); // snap back to the clamped truth (§11)
  }
  function onKvp(e: Event) {
    const el = e.target as HTMLInputElement;
    const v = parseFloat(el.value);
    if (Number.isFinite(v)) appState.setBeamKvp(v);
    el.value = String(appState.beamKvp);
  }
  function onFiltration(e: Event) {
    const el = e.target as HTMLInputElement;
    const v = parseFloat(el.value);
    if (Number.isFinite(v)) appState.setBeamFiltrationMmAl(v);
    el.value = String(appState.beamFiltrationMmAl);
  }

  // -- transmission vs energy: the stack's whole response, with the probe marked -----------
  // Log-log; the broad-beam (dose) curve above the narrow-beam (primary) one — their ratio IS
  // the buildup factor. An absorption edge (lead's 88 keV K-edge) shows as transmission FALLING
  // as energy rises, the one place the "higher energy penetrates more" rule of thumb inverts.
  function curveTraces(): Partial<Plotly.PlotData>[] {
    const c = probe?.curve;
    if (!c) return [];
    const xs = c.E_MeV.map((e) => e * 1e3);
    return [
      {
        x: xs,
        y: c.transmission_narrow,
        mode: "lines",
        line: { color: "#888", width: 1.5, dash: "dot" },
        name: "primary only",
        hovertemplate: "%{x:.3g} keV → %{y:.3e}<extra>narrow beam</extra>",
      } as Partial<Plotly.PlotData>,
      {
        x: xs,
        y: c.transmission,
        mode: "lines",
        line: { color: MODALITY_COLORS.gamma, width: 2 },
        name: "with buildup",
        hovertemplate: "%{x:.3g} keV → %{y:.3e}<extra>broad beam</extra>",
      } as Partial<Plotly.PlotData>,
    ];
  }

  function curveLayout(): Partial<Plotly.Layout> {
    const marks: Partial<Plotly.Shape>[] = [];
    if (mode === "line") {
      marks.push({
        type: "line",
        x0: appState.beamLineKeV,
        x1: appState.beamLineKeV,
        yref: "paper",
        y0: 0,
        y1: 1,
        line: { color: "#888", width: 1, dash: "dash" },
      });
    } else if (tube) {
      // the tube's scored span, source-endpoint down to the band floor
      marks.push({
        type: "rect",
        x0: tube.band_MeV[0] * 1e3,
        x1: Math.min(tube.endpoint_MeV, tube.band_MeV[1]) * 1e3,
        yref: "paper",
        y0: 0,
        y1: 1,
        fillcolor: "rgba(78,121,167,0.10)",
        line: { width: 0 },
      });
    }
    return {
      margin: { l: 62, r: 20, t: 10, b: 44 },
      showlegend: true,
      legend: { orientation: "h", y: -0.28 },
      xaxis: { type: "log", title: { text: "photon energy (keV)" }, automargin: true },
      yaxis: { type: "log", title: { text: "transmission" }, automargin: true },
      shapes: marks,
      autosize: true,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "currentColor" },
    };
  }

  // -- incident vs transmitted tube spectrum: beam hardening, drawn ------------------------
  function specTraces(): Partial<Plotly.PlotData>[] {
    if (!tube) return [];
    const xs = tube.spectrum.E_MeV.map((e) => e * 1e3);
    return [
      {
        x: xs,
        y: tube.spectrum.phi_in,
        mode: "lines",
        line: { color: "#888", width: 1.5 },
        name: "incident",
        hovertemplate: "%{x:.3g} keV<extra>incident</extra>",
      } as Partial<Plotly.PlotData>,
      {
        x: xs,
        y: tube.spectrum.phi_out,
        mode: "lines",
        fill: "tozeroy",
        fillcolor: "rgba(78,121,167,0.25)",
        line: { color: MODALITY_COLORS.gamma, width: 2 },
        name: `through ${stack || "the stack"}`,
        hovertemplate: "%{x:.3g} keV<extra>transmitted</extra>",
      } as Partial<Plotly.PlotData>,
    ];
  }

  function specLayout(): Partial<Plotly.Layout> {
    return {
      margin: { l: 62, r: 20, t: 10, b: 44 },
      showlegend: true,
      legend: { orientation: "h", y: -0.28 },
      xaxis: { title: { text: "photon energy (keV)" }, automargin: true },
      yaxis: { title: { text: "relative photons per bin" }, automargin: true },
      autosize: true,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: "currentColor" },
    };
  }

  $effect(() => {
    void probe;
    void appState.beamLineKeV;
    const el = curveEl;
    if (!el) return;
    if (mode === "off" || !probe) {
      Plotly.purge(el);
      return;
    }
    Plotly.react(el, curveTraces(), curveLayout(), { responsive: true, displaylogo: false });
  });

  $effect(() => {
    void probe;
    const el = specEl;
    if (!el) return;
    if (!tube) {
      Plotly.purge(el);
      return;
    }
    Plotly.react(el, specTraces(), specLayout(), { responsive: true, displaylogo: false });
  });

  onDestroy(() => {
    if (curveEl) Plotly.purge(curveEl);
    if (specEl) Plotly.purge(specEl);
  });
</script>

<div class="beam" data-testid="beam-probe">
  <div class="bar">
    <span class="muted">Test against a beam</span>
    <div class="modes" role="group" aria-label="Beam probe mode">
      <button class:on={mode === "off"} data-testid="beam-mode-off" onclick={() => appState.setBeamMode("off")}>Off</button>
      <button class:on={mode === "line"} data-testid="beam-mode-line" onclick={() => appState.setBeamMode("line")}>Single line</button>
      <button class:on={mode === "xray_tube"} data-testid="beam-mode-tube" onclick={() => appState.setBeamMode("xray_tube")}>X-ray tube</button>
    </div>
  </div>

  {#if mode !== "off"}
    <p class="note muted">
      Probes the stack above ({stack || "no layers — transmission is 1 by definition"}) with an
      <strong>external</strong> beam, independently of the loaded inventory. The answer is a
      <strong>transmission fraction</strong>, not a dose rate: the tool has no way to know an
      X-ray tube's output (mGy per mAs), and it will not invent one. Multiply your own
      <em>measured</em> unshielded reading by the transmission to get an absolute number.
    </p>

    {#if mode === "line"}
      <div class="controls">
        <label>
          Energy
          <input
            type="number"
            data-testid="beam-line-energy"
            min={band ? band[0] : 10}
            max={band ? band[1] : 15000}
            step="any"
            value={appState.beamLineKeV}
            onchange={onLineEnergy}
            onkeydown={(e) => e.key === "Enter" && onLineEnergy(e)}
          />
          <span class="muted">keV</span>
        </label>
        {#if band}
          <span class="muted small" data-testid="beam-band">scoreable {band[0].toFixed(0)}–{(band[1] / 1000).toFixed(0)}k keV</span>
        {/if}
        {#if presets.length > 0}
          <label>
            <span class="muted">from my source</span>
            <select
              aria-label="Probe at a line from the loaded inventory"
              data-testid="beam-line-preset"
              onchange={(e) => {
                const v = parseFloat((e.target as HTMLSelectElement).value);
                if (Number.isFinite(v)) appState.setBeamLineKeV(v);
              }}
            >
              <option value="">pick a line…</option>
              {#each presets as p (p.keV)}
                <option value={p.keV}>{p.label}</option>
              {/each}
            </select>
          </label>
        {/if}
      </div>
    {:else}
      <div class="controls">
        <label>
          Tube potential
          <input
            type="number"
            data-testid="beam-kvp"
            min="5"
            max="450"
            step="any"
            value={appState.beamKvp}
            onchange={onKvp}
            onkeydown={(e) => e.key === "Enter" && onKvp(e)}
          />
          <span class="muted">kV</span>
        </label>
        <label>
          Inherent filtration
          <input
            type="number"
            data-testid="beam-filtration"
            min="0"
            step="any"
            value={appState.beamFiltrationMmAl}
            onchange={onFiltration}
            onkeydown={(e) => e.key === "Enter" && onFiltration(e)}
          />
          <span class="muted">mm Al eq.</span>
        </label>
        <span class="muted small">tungsten anode · continuum only</span>
      </div>
    {/if}

    {#if appState.beamError}
      <p class="note error" role="alert" data-testid="beam-error">⚠ beam probe failed — {appState.beamError}</p>
    {:else if mode === "line" && line}
      <div class="cards">
        <div class="card" data-testid="beam-line-card" data-transmission={line.transmission}>
          <div class="card-h">Transmission at {keV(line.E_MeV)}</div>
          <div class="big">{frac(line.transmission)}</div>
          <div class="sub muted">
            of the beam's dose gets through — <strong>{frac(line.transmission_narrow)}</strong> as
            un-scattered primary, the rest added back by
            <Term term="buildup">buildup</Term> (B = {line.buildup == null ? "—" : line.buildup.toFixed(2)}).
            Depth {line.total_mfp.toFixed(2)} mean free paths.
          </div>
        </div>

        {#if detector}
          <div class="card" data-testid="beam-hvl-card">
            <div class="card-h">{cap(detector)} at this energy</div>
            <div class="row">
              <span class="muted"><Term term="half-value-layer">HVL</Term> (primary)</span>
              <strong>{thick(line.hvl_cm)}</strong>
            </div>
            <div class="row">
              <span class="muted">TVL (primary, ÷10)</span>
              <strong>{thick(line.tvl_cm)}</strong>
            </div>
            <div class="row big">
              <span class="muted">HVL for the <em>dose</em></span>
              <strong data-testid="beam-hvl-broad">{thick(line.hvl_broad_cm)}</strong>
            </div>
            <div class="sub muted">
              The dose HVL is the thicker one: halving the primary beam does not halve the dose,
              because scattered photons build back up. Quoted for the detector-side material.
            </div>
          </div>
        {/if}
      </div>

      {#if line.layers.length > 0}
        <table class="layers" data-testid="beam-layer-table">
          <thead>
            <tr><th>layer</th><th>cm</th><th>μ/ρ (cm²/g)</th><th>μ (cm⁻¹)</th><th>mfp</th></tr>
          </thead>
          <tbody>
            {#each line.layers as l, i (i)}
              <tr>
                <td>{cap(l.material)}</td>
                <td>{l.thickness_cm}</td>
                <td>{l.mu_rho_cm2_g.toPrecision(4)}</td>
                <td>{l.mu_cm1.toPrecision(4)}</td>
                <td>{l.mfp.toFixed(3)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}

      {#if line.buildup_capped}
        <p class="note approx" data-testid="beam-buildup-capped">
          Depth {line.total_mfp.toFixed(1)} mfp exceeds the ANS-6.4.3 fit range
          ({line.mfp_fit_max} mfp), so the buildup factor is frozen at its last valid value while
          the attenuation stays exact — the transmitted dose here is negligible either way (§11).
        </p>
      {/if}
    {:else if mode === "xray_tube" && tube}
      <div class="cards">
        <div class="card" data-testid="beam-tube-card" data-transmission={tube.transmission}>
          <div class="card-h">Transmission of a {tube.kvp} kVp beam</div>
          <div class="big">{frac(tube.transmission)}</div>
          <div class="sub muted">
            dose-weighted over the scored band ({(tube.band_MeV[0] * 1e3).toFixed(0)}–{(
              Math.min(tube.endpoint_MeV, tube.band_MeV[1]) * 1e3
            ).toFixed(0)} keV). Primary only: {frac(tube.transmission_narrow)}. Unlike a single
            line, this ratio depends on which dose quantity you weight it with — the response
            varies across the spectrum.
          </div>
        </div>

        <div class="card" data-testid="beam-hardening-card">
          <div class="card-h">Beam hardening</div>
          <div class="row">
            <span class="muted">mean energy</span>
            <strong>{keV(tube.mean_E_in_MeV)} → {keV(tube.mean_E_out_MeV)}</strong>
          </div>
          <div class="row">
            <span class="muted">HVL in aluminium</span>
            <strong data-testid="beam-hvl-al"
              >{tube.hvl_al_in_mm == null ? "—" : tube.hvl_al_in_mm.toFixed(2)} →
              {tube.hvl_al_out_mm == null ? "—" : tube.hvl_al_out_mm.toFixed(2)} mm</strong
            >
          </div>
          <div class="sub muted">
            The stack removes soft photons first, so what comes out is more penetrating than what
            went in: the surviving beam needs more aluminium to halve it. This is why a shield's
            "attenuation factor" is not one number you can reuse at another thickness.
          </div>
        </div>

        <div class="card" class:warn={tube.dropped_incident_fraction > 0.15} data-testid="beam-dropped-card">
          <div class="card-h">Outside the scored band</div>
          <div class="big" data-dropped={tube.dropped_incident_fraction}>{pct(tube.dropped_incident_fraction)}</div>
          <div class="sub muted">
            of the incident beam's air kerma sits below this stack's buildup floor
            ({(tube.band_MeV[0] * 1e3).toFixed(0)} keV) and is <strong>excluded</strong> from the
            ratio above, not counted as transmitted. Those are the softest photons — the ones the
            stack stops hardest — so the quoted transmission is an <strong>upper bound</strong> on
            the whole beam's. A big number here means the question was narrower than it looks.
          </div>
        </div>
      </div>

      <div class="bar-head"><span class="muted">Spectrum in vs out — the hardening, drawn</span></div>
      <div class="plot" data-testid="beam-spectrum-plot" bind:this={specEl}></div>
    {/if}

    <div class="bar-head">
      <span class="muted">
        Transmission vs energy for this stack — dose (with buildup) vs primary only
      </span>
    </div>
    <div class="plot" data-testid="beam-curve-plot" bind:this={curveEl}></div>

    <p class="hint muted">
      Same point-kernel physics as the dose panel, evaluated per energy rather than per decay:
      <em>B(E, Σμx)·exp(−Σμx)</em> from the bundled NIST μ/ρ and ANS-6.4.3 buildup data — a probe
      at one of your source's own line energies reconciles with the γ card exactly. Below a
      material's buildup floor (15 keV, 30 keV for lead) the shield is a
      <strong>data hole, not a transparent medium</strong>: the probe refuses those energies
      rather than assuming no scatter. <strong>Not for safety decisions</strong> (§11).
    </p>

    <LearnMore summary="What a beam probe tells you that a source dose does not">
      A dose calculation answers "how much does <em>my</em> source give me here". A beam probe
      answers "what does this wall <em>do</em>" — a property of the shield itself, so you can
      compare materials and thicknesses without picking a source at all. Two things surprise
      people. First, transmission is strongly energy-dependent: lead that stops a 60 keV X-ray
      almost perfectly is far leakier at 1 MeV, so "lead is good shielding" is only true relative
      to an energy. Second, a beam that gets through is not the beam that went in — the soft part
      is absorbed and the survivors are more penetrating, which is called
      <Term term="beam-hardening">beam hardening</Term>. That is why the second half-value layer
      is always thicker than the first.
      {#snippet advanced()}
        The X-ray tube here is an <em>idealized</em> continuum: Kramers' thick-target law
        (intensity ∝ E_max − E, so photon number ∝ (E_max − E)/E), shaped by the inherent
        filtration you enter in mm of aluminium equivalent, which also stands in for absorption in
        the anode itself. It carries <strong>no characteristic K lines</strong> (tungsten's appear
        above roughly 70 kVp) and no anode-angle detail, so treat the transmission-vs-energy shape
        and the hardening trend as meaningful and the absolute HVL in mm Al as indicative only —
        it is not a QA or compliance figure. Only a tungsten anode is offered: Mo/Rh mammography
        beams are dominated by their characteristic lines, which this model does not have.
      {/snippet}
    </LearnMore>
  {/if}
</div>

<style>
  .beam {
    margin-top: 1rem;
    border-top: 1px solid #8884;
    padding-top: 0.85rem;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }
  .bar > .muted {
    font-weight: 600;
  }
  .modes {
    display: inline-flex;
    border: 1px solid #8886;
    border-radius: 0.4rem;
    overflow: hidden;
  }
  .modes button {
    font: inherit;
    padding: 0.25rem 0.6rem;
    border: none;
    background: transparent;
    cursor: pointer;
  }
  .modes button + button {
    border-left: 1px solid #8886;
  }
  .modes button.on {
    background: #8883;
    font-weight: 600;
  }
  .controls {
    display: flex;
    gap: 1rem;
    align-items: center;
    flex-wrap: wrap;
    margin-top: 0.7rem;
  }
  .controls label {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.9rem;
  }
  input,
  select {
    font: inherit;
    padding: 0.25rem 0.4rem;
  }
  input[type="number"] {
    width: 6rem;
  }
  .cards {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin-top: 0.9rem;
  }
  .card {
    flex: 1 1 15rem;
    border: 1px solid #8884;
    border-radius: 0.5rem;
    padding: 0.6rem 0.8rem;
  }
  .card.warn {
    border-color: #8a6d0088;
    background: #8a6d000d;
  }
  .card-h {
    font-weight: 600;
    font-size: 0.9rem;
    margin-bottom: 0.35rem;
  }
  .big {
    font-size: 1.3rem;
    font-weight: 700;
    margin: 0.2rem 0;
    font-variant-numeric: tabular-nums;
  }
  .row {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    font-variant-numeric: tabular-nums;
    padding: 0.1rem 0;
  }
  .row.big {
    font-size: 1rem;
    border-top: 1px solid #8883;
    margin-top: 0.3rem;
    padding-top: 0.35rem;
  }
  .sub {
    font-size: 0.82rem;
  }
  .small {
    font-size: 0.82rem;
  }
  table.layers {
    margin-top: 0.8rem;
    border-collapse: collapse;
    font-size: 0.85rem;
    font-variant-numeric: tabular-nums;
  }
  table.layers th,
  table.layers td {
    text-align: right;
    padding: 0.2rem 0.6rem;
    border-bottom: 1px solid #8883;
  }
  table.layers th:first-child,
  table.layers td:first-child {
    text-align: left;
  }
  .bar-head {
    margin-top: 1rem;
    font-size: 0.9rem;
  }
  .plot {
    width: 100%;
    height: 240px;
    margin-top: 0.4rem;
  }
  .note {
    margin: 0.7rem 0 0;
    font-size: 0.88rem;
  }
  .note.error {
    color: #b3261e;
    font-weight: 600;
  }
  .note.approx {
    font-weight: 400;
    font-size: 0.85rem;
    opacity: 0.85;
    border-left: 3px solid #8884;
    padding-left: 0.6rem;
  }
  .muted {
    opacity: 0.7;
  }
  .hint {
    margin: 0.7rem 0 0;
    font-size: 0.85rem;
  }
</style>
