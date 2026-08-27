/**
 * Colour roles.
 *
 * The eight categorical slots are the validated default order. Eight is the
 * ceiling for the *adjacent* pairlist (stacked areas, lines) and this app only
 * uses them there. Anywhere every pair can end up side by side -- the
 * choropleth -- categorical colour is not used at all: the map encodes one
 * religion's magnitude on a single-hue sequential ramp, or change on a
 * diverging ramp. That is what keeps the map readable for colour-vision
 * deficiency without capping the chart at three religions.
 *
 * Validated with the skill's validator: light and dark both pass lightness,
 * chroma, CVD separation and normal-vision floors on adjacent pairs. Three
 * light-mode slots sit below 3:1 on the light surface, so the relief rule
 * applies -- the chart ships direct labels and a table view.
 */
export const CATEGORICAL_LIGHT = [
  "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
  "#e87ba4", "#008300", "#4a3aa7", "#e34948",
];

export const CATEGORICAL_DARK = [
  "#3987e5", "#d95926", "#199e70", "#c98500",
  "#d55181", "#008300", "#9085e9", "#e66767",
];

/** Single-hue blue ramp, light -> dark. Sequential magnitude only. */
export const SEQUENTIAL = [
  "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec",
  "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab",
  "#184f95", "#104281", "#0d366b",
];

/** Diverging blue <-> red with a neutral gray midpoint. Never a hue at the middle. */
export const DIVERGING = {
  negative: ["#0d366b", "#184f95", "#256abf", "#3987e5", "#86b6ef", "#cde2fb"],
  midpointLight: "#f0efec",
  midpointDark: "#383835",
  positive: ["#f8d0d0", "#f0a5a5", "#e66767", "#d03b3b", "#a82c2c", "#7d2020"],
};

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

export function categorical(dark: boolean): string[] {
  return dark ? CATEGORICAL_DARK : CATEGORICAL_LIGHT;
}

/** Sample the sequential ramp at t in [0,1]. */
export function sequentialAt(t: number): string {
  const i = Math.round(Math.max(0, Math.min(1, t)) * (SEQUENTIAL.length - 1));
  return SEQUENTIAL[i];
}

/**
 * Sample the diverging ramp. `t` in [-1, 1]; 0 is the neutral midpoint.
 * Equal step count per arm, so the two directions are visually comparable.
 */
export function divergingAt(t: number, dark: boolean): string {
  const mid = dark ? DIVERGING.midpointDark : DIVERGING.midpointLight;
  if (!Number.isFinite(t) || Math.abs(t) < 1e-6) return mid;
  const arm = t < 0 ? DIVERGING.negative : DIVERGING.positive;
  const mag = Math.min(1, Math.abs(t));
  // The arms run outward from the midpoint, so index from the light end.
  const i = Math.round(mag * (arm.length - 1));
  return t < 0 ? arm[arm.length - 1 - i] : arm[i];
}
