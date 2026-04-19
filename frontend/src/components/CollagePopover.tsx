import { useState } from "react";
import { Share2, X, Download, Loader2, RefreshCw } from "lucide-react";

interface CollagePopoverProps {
  /** API URL that returns JPEG collage bytes (grid param appended automatically) */
  url: string;
  label?: string;
  /** Total number of photos available — used to disable grid sizes that need more */
  photoCount: number;
}

const GRID_OPTIONS = [6, 5, 4, 3, 2] as const;

export function CollageButton({ url, label = "Collage", photoCount }: CollagePopoverProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [imgSrc, setImgSrc] = useState<string | null>(null);
  const [grid, setGrid] = useState(0); // 0 = not yet picked
  const [seed, setSeed] = useState(0);

  // Largest grid the photo count can fill
  const maxGrid = GRID_OPTIONS.find((s) => photoCount >= s * s) ?? 2;

  const fetchCollage = async (gridSize: number, s: number = seed) => {
    setLoading(true);
    if (imgSrc) URL.revokeObjectURL(imgSrc);
    setImgSrc(null);
    try {
      const sep = url.includes("?") ? "&" : "?";
      const res = await fetch(`${url}${sep}grid=${gridSize}&seed=${s}`);
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      setImgSrc(URL.createObjectURL(blob));
    } catch {
      setImgSrc(null);
    } finally {
      setLoading(false);
    }
  };

  const handleOpen = () => {
    const initial = grid || maxGrid;
    setGrid(initial);
    setOpen(true);
    fetchCollage(initial);
  };

  const handleGridChange = (size: number) => {
    setGrid(size);
    fetchCollage(size);
  };

  const handleClose = () => {
    setOpen(false);
    if (imgSrc) {
      URL.revokeObjectURL(imgSrc);
      setImgSrc(null);
    }
  };

  const handleDownload = () => {
    if (!imgSrc) return;
    const safeName = label
      .replace(/[^a-zA-Z0-9 _-]/g, "")
      .replace(/\s+/g, "_")
      .toLowerCase();
    const a = document.createElement("a");
    a.href = imgSrc;
    a.download = `${safeName}_${grid}x${grid}.jpg`;
    a.click();
  };

  return (
    <>
      <button
        onClick={handleOpen}
        className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors text-gray-400 hover:text-gray-600"
        title={label}
      >
        <Share2 className="w-4 h-4" />
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[3000] bg-black/80 flex items-center justify-center p-4"
          onClick={handleClose}
        >
          <div
            className="relative max-w-lg w-full bg-white rounded-xl overflow-hidden shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between p-3 border-b border-gray-100">
              <span className="text-sm font-medium text-gray-700">{label}</span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => {
                    const next = seed + 1;
                    setSeed(next);
                    fetchCollage(grid, next);
                  }}
                  disabled={loading}
                  className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-50"
                  title="Shuffle — different combination"
                >
                  <RefreshCw className={`w-4 h-4 text-gray-500 ${loading ? "animate-spin" : ""}`} />
                </button>
                {imgSrc && (
                  <button
                    onClick={handleDownload}
                    className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
                    title="Download"
                  >
                    <Download className="w-4 h-4 text-gray-500" />
                  </button>
                )}
                <button
                  onClick={handleClose}
                  className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
                >
                  <X className="w-4 h-4 text-gray-500" />
                </button>
              </div>
            </div>

            {/* Grid size selector */}
            <div className="flex items-center gap-1.5 px-3 py-2 border-b border-gray-100">
              <span className="text-xs text-gray-400 mr-1">Grid</span>
              {GRID_OPTIONS.map((size) => {
                const available = photoCount >= size * size;
                return (
                  <button
                    key={size}
                    onClick={() => available && handleGridChange(size)}
                    disabled={!available || loading}
                    title={
                      available
                        ? `${size}x${size} (${size * size} photos)`
                        : `Not enough photos — need ${size * size}, have ${photoCount}`
                    }
                    className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                      !available
                        ? "bg-gray-50 text-gray-300 cursor-not-allowed"
                        : grid === size
                          ? "bg-primary-600 text-white"
                          : "bg-gray-100 text-gray-500 hover:bg-gray-200"
                    } disabled:opacity-50`}
                  >
                    {size}x{size}
                  </button>
                );
              })}
            </div>

            {/* Image */}
            <div className="aspect-square bg-gray-100 flex items-center justify-center">
              {loading && <Loader2 className="w-8 h-8 animate-spin text-gray-400" />}
              {!loading && imgSrc && (
                <img src={imgSrc} alt="Collage" className="w-full h-full object-cover" />
              )}
              {!loading && !imgSrc && (
                <p className="text-sm text-gray-400">Could not generate collage</p>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
