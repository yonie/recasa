/**
 * Geometry of the photo grid, in one place: the column counts behind the
 * Tailwind classes, the thumbnail size a tile needs, and how tall a grid
 * will be before it is rendered.
 */
import { useSyncExternalStore } from "react";
import type { GridSize } from "../store/useStore";

// Columns at Tailwind's breakpoints: base, sm (640), md (768), lg (1024), xl (1280).
const BREAKPOINTS = [0, 640, 768, 1024, 1280];
const PREFIXES = ["", "sm:", "md:", "lg:", "xl:"];
const COLUMNS: Record<GridSize, number[]> = {
  S: [3, 4, 6, 8, 10],
  M: [2, 3, 4, 5, 6],
  L: [1, 2, 3, 3, 4],
};

// Matches the grid's p-4 and gap-1.5, and the sidebar's lg:w-64.
const PADDING = 16;
const GAP = 6;
const SIDEBAR_WIDTH = 256;
const SIDEBAR_BREAKPOINT = 1024;

/** "grid-cols-2 sm:grid-cols-3 ..."; these classes are safelisted in tailwind.config.ts. */
export function gridClasses(size: GridSize): string {
  return COLUMNS[size].map((n, i) => `${PREFIXES[i]}grid-cols-${n}`).join(" ");
}

function columnsAt(size: GridSize, viewportWidth: number): number {
  let cols = COLUMNS[size][0]!;
  BREAKPOINTS.forEach((bp, i) => {
    if (viewportWidth >= bp) cols = COLUMNS[size][i]!;
  });
  return cols;
}

/** Width of one square tile in CSS px, for a grid `containerWidth` wide. */
function tileWidth(size: GridSize, viewportWidth: number, containerWidth: number): number {
  const cols = columnsAt(size, viewportWidth);
  return (containerWidth - 2 * PADDING - (cols - 1) * GAP) / cols;
}

/**
 * Thumbnail size to request for a tile. The backend stores 200, 600 and 1200
 * px versions (long edge) and serves the next size up for anything else, so
 * only those are worth asking for. A 200 is enough while its short edge
 * (~150 px for a 4:3 photo) still covers the tile in device pixels; that is
 * the small grid on a standard-density screen, at a sixth of the bytes.
 * Anything larger gets 600, which is what every tile used before.
 */
export function gridThumbSize(size: GridSize): number {
  if (typeof window === "undefined") return 600;
  const devicePx = tileWidth(size, window.innerWidth, mainWidth()) * (window.devicePixelRatio || 1);
  return devicePx <= 150 ? 200 : 600;
}

/** Width of the content area beside the sidebar (which is a drawer below lg). */
function mainWidth(): number {
  const vw = window.innerWidth;
  return vw - (vw >= SIDEBAR_BREAKPOINT ? SIDEBAR_WIDTH : 0);
}

function subscribeResize(onChange: () => void) {
  window.addEventListener("resize", onChange);
  return () => window.removeEventListener("resize", onChange);
}

/** gridThumbSize, re-evaluated when the window (or its pixel density) changes. */
export function useGridThumbSize(size: GridSize): number {
  return useSyncExternalStore(
    subscribeResize,
    () => gridThumbSize(size),
    () => 600
  );
}

/** Height a full-width grid of `count` photos will take, for a placeholder before it renders. */
export function estimateGridHeight(size: GridSize, count: number): number {
  const vw = window.innerWidth;
  const cols = columnsAt(size, vw);
  const rows = Math.ceil(count / cols);
  return rows * tileWidth(size, vw, mainWidth()) + (rows - 1) * GAP + 2 * PADDING;
}
