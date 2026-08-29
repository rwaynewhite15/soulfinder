import { create } from "zustand";
import type { AppData } from "../lib/data";
import { snapToFrame } from "../lib/frames";

export type MapMetric = "share" | "change";
export type ChangeBasis = "share" | "people";
export type ChartMode = "stack" | "lines";
export type View = "globe" | "atlas";
export type ChartView = "series" | "trends";

export interface AppState {
  data: AppData | null;
  error: string | null;
  /** the frame grid, mirrored here so setYear can snap without the caller helping */
  years: number[];

  /** Currently scrubbed year. */
  year: number;
  /** Baseline year for the change metric. */
  baseYear: number;
  /** Brushed window on the time axis: [startYear, endYear]. */
  window: [number, number];

  /** Religion index driving the map ramp. */
  religion: number;
  /** Which religions are drawn in the chart. */
  visible: boolean[];

  /** Region whose series the chart shows: "WLD", an ISO3, or "USA-XX". */
  selected: string;
  hovered: string | null;

  /** Main stage: the single interactive globe, or the faceted atlas. */
  view: View;
  /** Lower pane: the time series, or the per-religion trend rail. */
  chartView: ChartView;

  mapMetric: MapMetric;
  changeBasis: ChangeBasis;
  chartMode: ChartMode;
  showDensity: boolean;
  showTable: boolean;
  dark: boolean;
  playing: boolean;
  /** wrap the timelapse back to the window start instead of stopping */
  loop: boolean;

  setData: (d: AppData) => void;
  setError: (e: string) => void;
  setYear: (y: number) => void;
  setBaseYear: (y: number) => void;
  setWindow: (w: [number, number]) => void;
  setReligion: (i: number) => void;
  toggleReligion: (i: number) => void;
  soloReligion: (i: number) => void;
  showAllReligions: () => void;
  select: (id: string) => void;
  hover: (id: string | null) => void;
  set: <K extends keyof AppState>(k: K, v: AppState[K]) => void;
}

const N_RELIGIONS = 8;

export const useStore = create<AppState>((set) => ({
  data: null,
  error: null,
  years: [],
  year: 2025,
  baseYear: 2010,
  // Opens on the full sweep, year 0 to 2050. The range brush zooms to any era.
  window: [0, 2050],
  religion: 0,
  visible: Array(N_RELIGIONS).fill(true),
  selected: "WLD",
  hovered: null,
  view: "globe",
  chartView: "series",
  mapMetric: "share",
  changeBasis: "share",
  chartMode: "stack",
  showDensity: false,
  showTable: false,
  dark: typeof window !== "undefined"
    && window.matchMedia?.("(prefers-color-scheme: dark)").matches,
  playing: false,
  loop: true,

  setData: (d) => set({ data: d, years: d.bundle.years }),
  setError: (e) => set({ error: e }),
  // Snap to a frame that actually carries data: the grid is non-uniform, so an
  // arbitrary year between knots has nothing to render.
  setYear: (y) => set((s) => ({ year: s.years.length ? snapToFrame(s.years, y) : y })),
  setBaseYear: (y) => set({ baseYear: y }),
  setWindow: (w) => set({ window: w }),
  setReligion: (i) => set({ religion: i }),
  toggleReligion: (i) =>
    set((s) => {
      const next = s.visible.slice();
      next[i] = !next[i];
      // Never let the chart empty out entirely -- an empty plot reads as a bug.
      return next.some(Boolean) ? { visible: next } : {};
    }),
  soloReligion: (i) =>
    set(() => ({ visible: Array.from({ length: N_RELIGIONS }, (_, j) => j === i) })),
  showAllReligions: () => set({ visible: Array(N_RELIGIONS).fill(true) }),
  select: (id) => set({ selected: id }),
  hover: (id) => set({ hovered: id }),
  set: (k, v) => set({ [k]: v } as Partial<AppState>),
}));
