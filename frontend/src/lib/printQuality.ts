// 200 DPI floor for a 10x15cm print: below this, prints look soft.
export const PRINT_MIN_LONG_EDGE = 1200;

// Standard consumer print sizes (cm), smallest first.
const PRINT_SIZES: [number, number][] = [
  [10, 15],
  [13, 18],
  [15, 20],
  [20, 30],
  [30, 45],
  [40, 60],
];

const CM_PER_INCH = 2.54;
const GOOD_DPI = 200;
const BORDERLINE_DPI = 150;

export interface PrintQuality {
  dpiAt10x15: number;
  /** Largest standard size that stays at or above 200 DPI, null if none. */
  maxGoodSize: [number, number] | null;
  level: "good" | "borderline" | "poor";
}

export function printQuality(width: number, height: number): PrintQuality {
  const longEdge = Math.max(width, height);
  const dpiAt10x15 = Math.round(longEdge / (15 / CM_PER_INCH));

  let maxGoodSize: [number, number] | null = null;
  for (const size of PRINT_SIZES) {
    const dpi = longEdge / (size[1] / CM_PER_INCH);
    if (dpi >= GOOD_DPI) maxGoodSize = size;
  }

  const level =
    dpiAt10x15 >= GOOD_DPI ? "good" : dpiAt10x15 >= BORDERLINE_DPI ? "borderline" : "poor";
  return { dpiAt10x15, maxGoodSize, level };
}

/** True when a photo's known resolution is below the 10x15cm print floor. */
export function isLowRes(p: { width: number | null; height: number | null }): boolean {
  const longEdge = Math.max(p.width ?? 0, p.height ?? 0);
  return longEdge > 0 && longEdge < PRINT_MIN_LONG_EDGE;
}

/** File format as the print export will deliver it. */
export function printFormatLabel(mimeType: string | null, fileName: string): string {
  const mime = (mimeType || "").toLowerCase();
  if (mime.includes("heic") || mime.includes("heif") || /\.hei[cf]$/i.test(fileName)) {
    return "HEIC → JPEG";
  }
  if (mime.includes("jpeg")) return "JPEG";
  if (mime.includes("png")) return "PNG";
  const ext = fileName.split(".").pop();
  return ext ? ext.toUpperCase() : "?";
}
