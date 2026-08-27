/**
 * sRGB <-> OKLab/OKLCH, and sequential ramp generation.
 *
 * Needed because the atlas gives each religion its own sequential ramp, and a
 * sequential ramp has exactly one hard requirement: monotone lightness. Naive
 * interpolation toward white in sRGB does not deliver that -- sRGB is not
 * perceptually uniform, so a "linear" fade produces steps that bunch up at one
 * end and a ramp whose apparent magnitude ordering does not match its values.
 * Interpolating lightness in OKLab, at fixed hue, does.
 */

type RGB = [number, number, number];

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

function srgbToLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}
function linearToSrgb(c: number): number {
  return c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055;
}

export function hexToRgb01(hex: string): RGB {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16) / 255,
    parseInt(h.slice(2, 4), 16) / 255,
    parseInt(h.slice(4, 6), 16) / 255,
  ];
}

export function rgb01ToHex([r, g, b]: RGB): string {
  const to = (c: number) =>
    Math.round(clamp01(c) * 255).toString(16).padStart(2, "0");
  return `#${to(r)}${to(g)}${to(b)}`;
}

/** sRGB (0-1) -> OKLab. Björn Ottosson's matrices. */
export function rgbToOklab([r, g, b]: RGB): [number, number, number] {
  const lr = srgbToLinear(r), lg = srgbToLinear(g), lb = srgbToLinear(b);
  const l = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
  const m = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
  const s = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

export function oklabToRgb([L, a, bb]: [number, number, number]): RGB {
  const l = (L + 0.3963377774 * a + 0.2158037573 * bb) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * bb) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * bb) ** 3;
  return [
    linearToSrgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    linearToSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    linearToSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
}

export function toOklch(hex: string): { L: number; C: number; h: number } {
  const [L, a, b] = rgbToOklab(hexToRgb01(hex));
  return { L, C: Math.hypot(a, b), h: Math.atan2(b, a) };
}

function inGamut([r, g, b]: RGB, eps = 1e-4): boolean {
  return r >= -eps && r <= 1 + eps && g >= -eps && g <= 1 + eps && b >= -eps && b <= 1 + eps;
}

/**
 * OKLCH -> hex, gamut-mapped by reducing chroma.
 *
 * A requested (L, C, h) is often outside sRGB -- saturated yellow at low
 * lightness especially. Clamping the RGB channels, the obvious fix, clips them
 * unequally and so rotates the hue: measured drift was up to 30 degrees across
 * a single ramp, which turns a one-hue sequential scale into a small rainbow.
 * Binary-searching chroma down to the gamut boundary instead holds L and h
 * exactly and gives up only saturation, which is the one of the three the
 * reader is not decoding.
 */
export function fromOklch(L: number, C: number, h: number): string {
  const at = (c: number): RGB => oklabToRgb([L, c * Math.cos(h), c * Math.sin(h)]);
  if (inGamut(at(C))) return rgb01ToHex(at(C));
  let lo = 0, hi = C;
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2;
    if (inGamut(at(mid))) lo = mid; else hi = mid;
  }
  return rgb01ToHex(at(lo));
}

/**
 * Build an n-step sequential ramp from a categorical hue.
 *
 * Hue is held fixed, so the ramp reads as one colour getting stronger --
 * the identity of the series is carried by the hue, magnitude by lightness.
 * Chroma is tapered toward the light end because a near-white step at full
 * chroma reads as a distinct pastel hue rather than as "almost none".
 *
 * `dark` flips the anchor: on a dark surface the low end must be the dark step,
 * or "near zero" ends up as the brightest thing on screen.
 */
export function sequentialRamp(baseHex: string, steps = 9, dark = false): string[] {
  const { C, h } = toOklch(baseHex);
  const lo = dark ? 0.24 : 0.93;   // near-zero end, closest to the surface
  const hi = dark ? 0.88 : 0.38;   // full-magnitude end
  return Array.from({ length: steps }, (_, i) => {
    const t = i / (steps - 1);
    const L = lo + (hi - lo) * t;
    // taper chroma at the low end so it recedes instead of reading as a tint
    const c = C * (0.34 + 0.66 * t);
    return fromOklch(L, c, h);
  });
}

/** Sample a ramp at t in [0,1]. */
export function rampAt(ramp: string[], t: number): string {
  const i = Math.round(clamp01(t) * (ramp.length - 1));
  return ramp[i];
}
