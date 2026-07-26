// Shared display formatting for quantities (masses/activities). Display only — the
// stored `entries[].quantity` always keeps the full input accuracy, so a digit change
// is never a silent physics edit (§11). Two consumers with one rule: the Sources
// review panel (grouped, read-only text) and the Inventory quantity cells.

/**
 * Fixed-decimal rendering with `digits` digits AFTER the decimal point (NOT significant
 * figures — the sig-fig helpers in `dosemath.ts` are deliberately separate, since dose
 * spans many decades and wants sig-figs on purpose).
 *
 * Falls back to scientific notation at the extremes: very large values, and — the
 * honesty half — values the chosen digit count could not show at all. At 0 digits a
 * 0.004 g line would render "0", which reads as "nothing is there"; 4.000e-3 keeps a
 * small quantity visible at every setting.
 *
 * `group: false` drops the thousands separators, which an `<input type="number">`
 * cannot parse ("1,000.000" is not a valid floating-point value and blanks the field).
 */
export function fmtQuantity(v: number, digits: number, opts: { group?: boolean } = {}): string {
  if (!Number.isFinite(v)) return String(v);
  const av = Math.abs(v);
  if (av !== 0 && (av < 1e-3 || av < 0.5 * 10 ** -digits || av >= 1e9)) return v.toExponential(3);
  return opts.group === false
    ? v.toFixed(digits)
    : v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
