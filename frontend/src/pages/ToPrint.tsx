import { useState, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, printExportUrl, thumbnailUrl, type PhotoSummary } from "../api/client";
import { useStore, type GridSize } from "../store/useStore";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { GridViewControls } from "../components/PhotoGrid";
import { Loader2, Printer, Download, ListX } from "lucide-react";
import { clsx } from "clsx";

const CARD_GRID_CLASSES: Record<GridSize, string> = {
  S: "grid-cols-3 sm:grid-cols-4 md:grid-cols-5 xl:grid-cols-6",
  M: "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5",
  L: "grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-3",
};

// 200 DPI floor for a 10x15cm print — below this, prints look soft.
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

interface PrintQuality {
  dpiAt10x15: number;
  /** Largest standard size that stays at or above 200 DPI, null if none. */
  maxGoodSize: [number, number] | null;
  level: "good" | "borderline" | "poor";
}

function printQuality(width: number, height: number): PrintQuality {
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

function formatLabel(mimeType: string | null, fileName: string): string {
  const mime = (mimeType || "").toLowerCase();
  if (mime.includes("heic") || mime.includes("heif") || /\.hei[cf]$/i.test(fileName)) {
    return "HEIC → JPEG";
  }
  if (mime.includes("jpeg")) return "JPEG";
  if (mime.includes("png")) return "PNG";
  const ext = fileName.split(".").pop();
  return ext ? ext.toUpperCase() : "?";
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export function ToPrint() {
  const [clearing, setClearing] = useState(false);
  const openPhoto = useOpenPhoto();
  const setStats = useStore((s) => s.setStats);
  const gridSize = useStore((s) => s.gridSize);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["photos", { marked_for_print: true }],
    queryFn: () => api.getPhotos({ marked_for_print: true, page_size: 200 }),
  });
  const photos = data?.items ?? [];

  const handlePhotoClick = useCallback(
    (photo: PhotoSummary, index: number) => openPhoto(photo, index, photos),
    [openPhoto, photos]
  );

  const handleRemove = useCallback(
    async (photo: PhotoSummary) => {
      try {
        await api.togglePrint(photo.file_hash);
        api.getStats().then(setStats).catch(() => {});
        queryClient.invalidateQueries();
      } catch {
        // ignore
      }
    },
    [queryClient, setStats]
  );

  const handleRemoveAll = useCallback(async () => {
    const count = photos.length;
    if (
      !window.confirm(
        `Remove all ${count} photo${count !== 1 ? "s" : ""} from the To Print list? ` +
          "Your photos are not deleted."
      )
    ) {
      return;
    }
    try {
      setClearing(true);
      await api.clearPrintList();
      api.getStats().then(setStats).catch(() => {});
      await queryClient.invalidateQueries();
    } catch {
      // ignore
    } finally {
      setClearing(false);
    }
  }, [photos.length, queryClient, setStats]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  if (photos.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
        <Printer className="w-12 h-12 text-gray-300" />
        <p className="text-lg">Nothing to print yet</p>
        <p className="text-sm">
          Hover over photos and click the printer icon, or press P while viewing
        </p>
      </div>
    );
  }

  const lowResCount = photos.filter((p) => {
    const longEdge = Math.max(p.width ?? 0, p.height ?? 0);
    return longEdge > 0 && longEdge < PRINT_MIN_LONG_EDGE;
  }).length;

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold">
          To Print
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {photos.length} photo{photos.length !== 1 ? "s" : ""}
          </span>
        </h1>
        {lowResCount > 0 && (
          <span className="text-xs text-amber-600 bg-amber-50 px-2 py-1 rounded-full">
            {lowResCount} photo{lowResCount !== 1 ? "s" : ""} may be too small to print well
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <a
            href={printExportUrl()}
            download
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary-600 text-white
                       text-sm font-medium hover:bg-primary-700 transition-colors"
          >
            <Download className="w-4 h-4" />
            Download zip
          </a>
          <button
            onClick={handleRemoveAll}
            disabled={clearing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200
                       text-sm text-gray-600 hover:bg-gray-100 transition-colors disabled:opacity-50"
          >
            {clearing ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <ListX className="w-4 h-4" />
            )}
            Remove all from list
          </button>
        </div>
      </div>

      <div className={clsx("grid gap-4 p-4", CARD_GRID_CLASSES[gridSize])}>
        {photos.map((photo, index) => (
          <PrintCard
            key={photo.file_hash}
            photo={photo}
            onClick={() => handlePhotoClick(photo, index)}
            onRemove={() => handleRemove(photo)}
          />
        ))}
      </div>
      <GridViewControls />
    </div>
  );
}

interface PrintCardProps {
  photo: PhotoSummary;
  onClick: () => void;
  onRemove: () => void;
}

function PrintCard({ photo, onClick, onRemove }: PrintCardProps) {
  const gridFit = useStore((s) => s.gridFit);
  const hasResolution = !!photo.width && !!photo.height;
  const quality = hasResolution ? printQuality(photo.width!, photo.height!) : null;
  const megapixels = hasResolution ? (photo.width! * photo.height!) / 1_000_000 : 0;

  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden group">
      <div className="relative aspect-square bg-gray-100 cursor-pointer" onClick={onClick}>
        <img
          src={thumbnailUrl(photo.file_hash, 600)}
          alt={photo.file_name}
          loading="lazy"
          className={clsx("w-full h-full", gridFit === "square" ? "object-cover" : "object-contain")}
        />
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="absolute top-2 right-2 p-1.5 rounded-full bg-black/40 text-white
                     opacity-100 sm:opacity-0 sm:group-hover:opacity-100
                     hover:bg-black/60 transition-all"
          title="Remove from list"
        >
          <Printer className="w-4 h-4 fill-sky-400 text-sky-400" />
        </button>
      </div>

      <div className="p-2.5 space-y-1 text-xs">
        <p className="font-medium text-gray-700 truncate" title={photo.file_name}>
          {photo.file_name}
        </p>
        <p className="text-gray-500">
          {hasResolution ? (
            <>
              {photo.width} × {photo.height} · {megapixels.toFixed(1)} MP
            </>
          ) : (
            "Resolution unknown"
          )}
        </p>
        <p className="text-gray-500">
          {formatBytes(photo.file_size)} · {formatLabel(photo.mime_type, photo.file_name)}
        </p>
        {quality && (
          <p
            className={clsx(
              "font-medium",
              quality.level === "good" && "text-green-600",
              quality.level === "borderline" && "text-amber-600",
              quality.level === "poor" && "text-red-600"
            )}
          >
            {quality.dpiAt10x15} DPI at 10×15
            {quality.level === "good" && quality.maxGoodSize && (
              <> · good up to {quality.maxGoodSize[0]}×{quality.maxGoodSize[1]} cm</>
            )}
            {quality.level === "borderline" && <> · borderline for printing</>}
            {quality.level === "poor" && <> · too small to print well</>}
          </p>
        )}
      </div>
    </div>
  );
}
