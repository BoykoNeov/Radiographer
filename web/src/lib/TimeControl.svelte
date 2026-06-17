<script lang="ts">
  // Time control (M6-ui M6d, §9): a single LOG time slider, auto-ranged per
  // inventory (from the solve's `time_range_s`), with one half-life tick per
  // species; a numeric "go to" entry + unit; the definable source-age t₀; and a
  // play/pause animate that sweeps equal LOG-time steps. Every control here only
  // moves a CURSOR over the already-solved curves — it never re-solves (§3). The
  // store owns the state; this component is the cursor's driver + the animate loop.
  //
  // The cursor's absolute decay time (what the DAG/dose will read in M6e/M6f) is
  // `appState.currentTimeS = referenceTimeS + cursorOffsetS`. t₀ is the M6d wiring
  // of the M6b-stored offset: "forward decay is free" (§8/§9), so changing it
  // re-evaluates (cheap) but never re-solves.
  import { onDestroy } from "svelte";
  import { appState } from "./state.svelte";
  import { DEFAULT_TIME_UNIT, TIME_UNITS, humanTime, toSeconds } from "./types";

  // -- log slider mapping ----------------------------------------------------
  // HTML range inputs are linear, so the slider operates in log10(seconds) space.
  const range = $derived(appState.cursorRange); // [lo, hi] display seconds, or null
  const lo = $derived(range ? range[0] : 0); // numeric, for template (TS can't narrow range there)
  const hi = $derived(range ? range[1] : 1);
  const logLo = $derived(range ? Math.log10(range[0]) : 0);
  const logHi = $derived(range ? Math.log10(range[1]) : 1);
  const sliderPos = $derived(
    appState.cursorOffsetS > 0 ? Math.log10(appState.cursorOffsetS) : logLo,
  );
  const STEP = $derived((logHi - logLo) / 1000);

  function onSlider(ev: Event) {
    stopAnim(); // a manual scrub cancels an in-flight sweep
    appState.setCursorOffsetS(10 ** (ev.target as HTMLInputElement).valueAsNumber);
  }

  // One half-life tick per finite-half-life species, positioned in the SAME
  // display-time coordinate as the slider/curves (exact when t₀=0). Shared palette.
  const ticks = $derived.by(() => {
    if (!range) return [];
    const hl = appState.solveMeta?.half_lives_s ?? {};
    const span = logHi - logLo || 1;
    return appState.closure
      .map((n) => ({ name: n, h: hl[n] }))
      .filter((t): t is { name: string; h: number } => typeof t.h === "number" && t.h > 0)
      .map((t) => ({
        name: t.name,
        h: t.h,
        pct: ((Math.log10(t.h) - logLo) / span) * 100,
        color: appState.colors[t.name] ?? "#888",
      }))
      .filter((t) => t.pct >= 0 && t.pct <= 100);
  });

  // -- numeric "go to" entry (display time since t₀) -------------------------
  let gotoVal = $state<number | null>(null);
  let gotoUnit = $state(DEFAULT_TIME_UNIT);
  function onGoto() {
    if (gotoVal === null || !Number.isFinite(gotoVal)) return;
    stopAnim();
    appState.setCursorOffsetS(toSeconds(gotoVal, gotoUnit));
  }

  // -- source-age (t₀) entry -------------------------------------------------
  let ageVal = $state<number | null>(null);
  let ageUnit = $state("y");
  function onAge() {
    const v = ageVal ?? 0;
    appState.setReferenceTimeS(Number.isFinite(v) ? toSeconds(v, ageUnit) : 0); // re-evaluates, never re-solves
  }

  // -- animate (equal log-time sweep) ---------------------------------------
  // Cancellable three ways (advisor): manual scrub (stopAnim above), inventory
  // change (solve() clears appState.animating → the guard $effect clears the
  // timer), and unmount (onDestroy). The tick also bails if the flag went false.
  const FRAME_MS = 40;
  const SWEEP_STEPS = 140;
  let timer: ReturnType<typeof setInterval> | null = null;

  function tick() {
    if (!appState.animating || !range) {
      stopAnim();
      return;
    }
    const step = (logHi - logLo) / SWEEP_STEPS;
    const next = Math.log10(appState.cursorOffsetS) + step;
    if (next >= logHi) {
      appState.setCursorOffsetS(range[1]);
      stopAnim();
      return;
    }
    appState.setCursorOffsetS(10 ** next);
  }

  function startAnim() {
    if (!range) return;
    // Restart from the beginning if the cursor is already at/near the end.
    if (appState.cursorOffsetS >= range[1] * 0.999) appState.setCursorOffsetS(range[0]);
    appState.animating = true;
    timer = setInterval(tick, FRAME_MS);
  }

  function stopAnim() {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
    appState.animating = false;
  }

  function toggleAnim() {
    if (appState.animating) stopAnim();
    else startAnim();
  }

  // External cancel: if the store turned `animating` off (a re-solve did) while
  // our timer is still live, tear the timer down. Keeps the loop from outliving
  // the handle it evaluates against.
  $effect(() => {
    if (!appState.animating && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  });

  onDestroy(stopAnim);

  const hasRange = $derived(range !== null);
</script>

{#if appState.solveMeta}
  <section class="time" data-testid="time-control">
    <header>
      <h2>Time</h2>
      <span class="readout" data-testid="time-readout">
        cursor: <strong>{humanTime(appState.cursorOffsetS)}</strong>
        {#if appState.referenceTimeS > 0}
          after t₀ · absolute age <strong>{humanTime(appState.currentTimeS)}</strong>
        {/if}
      </span>
    </header>

    {#if !hasRange}
      <p class="note muted">
        All loaded nuclides are stable — there is no time evolution to scrub.
      </p>
    {:else}
      <!-- Log slider + half-life ticks -->
      <div class="slider-wrap">
        <input
          class="time-slider"
          data-testid="time-slider"
          type="range"
          min={logLo}
          max={logHi}
          step={STEP}
          value={sliderPos}
          oninput={onSlider}
          aria-label="Time cursor (log scale)"
        />
        <div class="ticks" data-testid="halflife-ticks">
          {#each ticks as t (t.name)}
            <span
              class="tick"
              style="left:{t.pct}%; background:{t.color}"
              title="{t.name} half-life: {humanTime(t.h)}"
            ></span>
          {/each}
        </div>
        <div class="scale muted">
          <span>{humanTime(lo)}</span>
          <span>{humanTime(hi)}</span>
        </div>
      </div>

      <!-- Controls: animate, go-to, source-age -->
      <div class="controls">
        <button class="play" data-testid="time-play" onclick={toggleAnim}>
          {appState.animating ? "⏸ Pause" : "▶ Animate"}
        </button>

        <label class="goto">
          Go to t₀+
          <input
            type="number"
            min="0"
            step="any"
            placeholder="time"
            bind:value={gotoVal}
            onkeydown={(e) => e.key === "Enter" && onGoto()}
          />
          <select data-testid="time-goto-unit" bind:value={gotoUnit}>
            {#each TIME_UNITS as u (u.value)}
              <option value={u.value}>{u.label}</option>
            {/each}
          </select>
          <button data-testid="time-goto" onclick={onGoto}>Go</button>
        </label>

        <label class="age" title="Source-age / reference origin t₀ — an evaluation offset (§8/§9), not a re-solve.">
          Source age t₀:
          <input
            type="number"
            min="0"
            step="any"
            placeholder="0"
            bind:value={ageVal}
            onkeydown={(e) => e.key === "Enter" && onAge()}
          />
          <select data-testid="source-age-unit" bind:value={ageUnit}>
            {#each TIME_UNITS as u (u.value)}
              <option value={u.value}>{u.label}</option>
            {/each}
          </select>
          <button data-testid="source-age" onclick={onAge}>Set</button>
          <span class="muted cur">now: {humanTime(appState.referenceTimeS)}</span>
        </label>
      </div>

      <p class="hint muted">
        The slider scrubs a cursor over the curves above — one Bateman solve,
        evaluated many (§3); nothing re-solves. Ticks mark each species' half-life.
        Source age t₀ shifts the evaluation origin forward (free forward decay,
        §8/§9), so the cursor's absolute decay time is t₀ + the slider position.
      </p>
    {/if}
  </section>
{/if}

<style>
  .time {
    border: 1px solid #8884;
    border-radius: 0.5rem;
    padding: 1rem;
    margin-top: 1rem;
  }
  header {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    flex-wrap: wrap;
  }
  h2 {
    margin: 0;
    font-size: 1.05rem;
    margin-right: auto;
  }
  .readout {
    font-size: 0.9rem;
    opacity: 0.85;
  }
  .slider-wrap {
    margin-top: 0.75rem;
  }
  .time-slider {
    width: 100%;
    display: block;
  }
  .ticks {
    position: relative;
    height: 0.9rem;
    margin-top: 0.15rem;
  }
  .tick {
    position: absolute;
    top: 0;
    width: 2px;
    height: 0.7rem;
    transform: translateX(-1px);
    border-radius: 1px;
  }
  .scale {
    display: flex;
    justify-content: space-between;
    font-size: 0.8rem;
    margin-top: 0.1rem;
  }
  .controls {
    display: flex;
    gap: 1rem;
    align-items: center;
    flex-wrap: wrap;
    margin-top: 0.75rem;
  }
  .controls label {
    display: inline-flex;
    gap: 0.35rem;
    align-items: center;
  }
  input,
  select,
  button {
    font: inherit;
    padding: 0.3rem 0.5rem;
  }
  .goto input,
  .age input {
    width: 6rem;
  }
  .play {
    font-weight: 600;
  }
  .cur {
    font-size: 0.85rem;
  }
  .note {
    margin: 0.75rem 0 0;
  }
  .muted {
    opacity: 0.7;
  }
  .hint {
    margin: 0.6rem 0 0;
    font-size: 0.85rem;
  }
</style>
