import { useCallback, useEffect, useState, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Star, Play, Printer, Flag, Grid2x2, Grid3x3, LayoutGrid, Crop, Expand, Loader2 } from "lucide-react";
import { clsx } from "clsx";
import type { PhotoSummary } from "../api/client";
import { api, thumbnailUrl, livePhotoUrl, formatDuration } from "../api/client";
import { useStore, type GridSize } from "../store/useStore";

const GRID_CLASSES: Record<GridSize, string> = {
  S: "grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10",
  M: "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6",
  L: "grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4",
};

// Exported so the viewer can reuse the exact URL the grid already fetched —
// that cache hit is what makes its placeholder appear with no network wait.
export const THUMB_SIZE: Record<GridSize, number> = { S: 300, M: 600, L: 600 };

interface PhotoGridProps {
  photos: PhotoSummary[];
  onPhotoClick: (photo: PhotoSummary, index: number) => void;
  onFavoriteToggle?: (photo: PhotoSummary) => void;
  onPrintToggle?: (photo: PhotoSummary) => void;
  /** Persistent printer mark on marked thumbnails (off on the To Print page itself). */
  showPrintMark?: boolean;
  /** Render the floating size/fit controls. Set false when a page shows many
   *  grids (month groups) and renders GridViewControls once itself. */
  showControls?: boolean;
}

/** Touch devices never hover, so live-photo <video> elements would be dead
 *  weight there — iOS Safari slows to a crawl with many media elements. */
const HOVER_CAPABLE =
  typeof window !== "undefined" &&
  window.matchMedia("(hover: hover) and (pointer: fine)").matches;

const GRID_CYCLE: GridSize[] = ["S", "M", "L"];
const GRID_ICON = { S: LayoutGrid, M: Grid3x3, L: Grid2x2 } as const;

function GridSizeToggle() {
  const gridSize = useStore((s) => s.gridSize);
  const setGridSize = useStore((s) => s.setGridSize);
  const Icon = GRID_ICON[gridSize];

  const cycle = () => {
    const idx = GRID_CYCLE.indexOf(gridSize);
    const next = GRID_CYCLE[(idx + 1) % GRID_CYCLE.length] as GridSize;
    setGridSize(next);
  };

  return (
    <button
      onClick={cycle}
      className="w-10 h-10 rounded-full bg-white/95 shadow-lg
                 border border-gray-200 flex items-center justify-center
                 hover:bg-gray-100 transition-colors"
      title={`Grid size: ${gridSize}`}
    >
      <Icon className="w-5 h-5 text-gray-600" />
    </button>
  );
}

function GridFitToggle() {
  const gridFit = useStore((s) => s.gridFit);
  const setGridFit = useStore((s) => s.setGridFit);

  return (
    <button
      onClick={() => setGridFit(gridFit === "square" ? "full" : "square")}
      className="w-10 h-10 rounded-full bg-white/95 shadow-lg
                 border border-gray-200 flex items-center justify-center
                 hover:bg-gray-100 transition-colors"
      title={gridFit === "square" ? "Showing cropped squares — click for full photos" : "Showing full photos — click for cropped squares"}
    >
      {gridFit === "square" ? (
        <Crop className="w-5 h-5 text-gray-600" />
      ) : (
        <Expand className="w-5 h-5 text-gray-600" />
      )}
    </button>
  );
}

/** Floating grid display controls (size + square/full fit), shared by all grid pages. */
export function GridViewControls() {
  return (
    <div className="fixed bottom-4 right-4 z-30 flex flex-col gap-2">
      <GridFitToggle />
      <GridSizeToggle />
    </div>
  );
}

export function PhotoGrid({
  photos,
  onPhotoClick,
  onFavoriteToggle,
  onPrintToggle,
  showPrintMark = true,
  showControls = true,
}: PhotoGridProps) {
  const gridSize = useStore((s) => s.gridSize);

  if (photos.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <p>No photos found</p>
      </div>
    );
  }

  return (
    <>
      <div className={clsx("photo-grid grid gap-1.5 p-4", GRID_CLASSES[gridSize])}>
        {photos.map((photo, index) => (
          <PhotoGridItem
            key={photo.file_hash}
            photo={photo}
            onClick={() => onPhotoClick(photo, index)}
            onFavoriteToggle={onFavoriteToggle}
            onPrintToggle={onPrintToggle}
            showPrintMark={showPrintMark}
            thumbSize={THUMB_SIZE[gridSize]}
          />
        ))}
      </div>
      {showControls && <GridViewControls />}
    </>
  );
}

interface PhotoGridItemProps {
  photo: PhotoSummary;
  onClick: () => void;
  onFavoriteToggle?: (photo: PhotoSummary) => void;
  onPrintToggle?: (photo: PhotoSummary) => void;
  showPrintMark: boolean;
  thumbSize: number;
}

function PhotoGridItem({
  photo,
  onClick,
  onFavoriteToggle,
  onPrintToggle,
  showPrintMark,
  thumbSize,
}: PhotoGridItemProps) {
  const [isHovering, setIsHovering] = useState(false);
  const [isFavorite, setIsFavorite] = useState(photo.is_favorite);
  const [isMarkedForPrint, setIsMarkedForPrint] = useState(photo.marked_for_print);
  const [isFlagging, setIsFlagging] = useState(false);
  const [isFavoriting, setIsFavoriting] = useState(false);
  const [isPrinting, setIsPrinting] = useState(false);
  const setStats = useStore((s) => s.setStats);
  const queryClient = useQueryClient();
  const gridFit = useStore((s) => s.gridFit);
  const fitClass = gridFit === "square" ? "object-cover" : "object-contain";
  const videoRef = useRef<HTMLVideoElement>(null);

  const handleFavorite = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      if (isFavoriting) return;
      // The tile stays put here, so the spinner only has to cover the POST:
      // the filled star is the acknowledgement from the moment it lands. Not
      // awaited past that, or it would spin on through the blanket refetch
      // long after the answer is on screen.
      setIsFavoriting(true);
      try {
        const result = await api.toggleFavorite(photo.file_hash);
        setIsFavorite(result.is_favorite);
        onFavoriteToggle?.(photo);
        // Single-user app: blanket invalidation is cheap and always correct.
        queryClient.invalidateQueries();
      } catch {
        // ignore
      } finally {
        setIsFavoriting(false);
      }
    },
    [photo, isFavoriting, onFavoriteToggle, queryClient]
  );

  const handlePrint = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      if (isPrinting) return;
      setIsPrinting(true);
      try {
        const result = await api.togglePrint(photo.file_hash);
        setIsMarkedForPrint(result.marked_for_print);
        onPrintToggle?.(photo);
        api.getStats().then(setStats).catch(() => {});
        queryClient.invalidateQueries();
      } catch {
        // ignore
      } finally {
        setIsPrinting(false);
      }
    },
    [photo, isPrinting, onPrintToggle, setStats, queryClient]
  );

  const handleFlag = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      if (isFlagging) return;
      // The tile only disappears once the refetch lands, which is a beat or two
      // after the click. Show the spinner for that whole window — stopping it
      // when the POST returns would just restore the unresponsive-looking gap.
      setIsFlagging(true);
      try {
        await api.toggleFlag(photo.file_hash);
        // Flagged photos leave normal views; refetch removes the tile.
        api.getStats().then(setStats).catch(() => {});
        await queryClient.invalidateQueries();
      } catch {
        // ignore
      } finally {
        setIsFlagging(false);
      }
    },
    [photo, isFlagging, setStats, queryClient]
  );


  const [everHovered, setEverHovered] = useState(false);

  const handleMouseEnter = useCallback(() => {
    setIsHovering(true);
    setEverHovered(true);
  }, []);

  const handleMouseLeave = useCallback(() => {
    setIsHovering(false);
  }, []);

  const [videoFailed, setVideoFailed] = useState(false);
  const showVideo = isHovering && photo.has_live_photo && !videoFailed;
  // Mount the video lazily on first hover; keep it mounted afterwards so
  // re-hovering doesn't re-fetch.
  const mountVideo =
    HOVER_CAPABLE && everHovered && photo.has_live_photo && !videoFailed;

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (showVideo) {
      video.play().catch(() => {});
    } else {
      video.pause();
      video.currentTime = 0;
    }
  }, [showVideo]);

  return (
    <div
      className="photo-grid-item aspect-square bg-gray-100 group"
      onClick={onClick}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <img
        src={thumbnailUrl(photo.file_hash, thumbSize)}
        alt={photo.file_name}
        loading="lazy"
        decoding="async"
        className={clsx(
          "w-full h-full",
          HOVER_CAPABLE && "transition-opacity duration-200",
          fitClass,
          showVideo && "opacity-0"
        )}
      />

      {/* Live Photo video overlay (mounted on first hover; never on touch) */}
      {mountVideo && (
        <video
          ref={videoRef}
          src={livePhotoUrl(photo.file_hash)}
          className={clsx(
            "absolute inset-0 w-full h-full",
            fitClass,
            showVideo ? "opacity-100" : "opacity-0"
          )}
          muted
          loop
          playsInline
          preload="none"
          onError={() => setVideoFailed(true)}
        />
      )}

      {/* Video duration badge */}
      {photo.is_video && (
        <div className="absolute bottom-1.5 right-1.5 z-10 flex items-center gap-1 px-1.5 py-0.5 rounded bg-black/60 pointer-events-none">
          <Play className="w-3 h-3 text-white fill-white" />
          {photo.duration ? (
            <span className="text-white text-[10px] font-medium tabular-nums">
              {formatDuration(photo.duration)}
            </span>
          ) : null}
        </div>
      )}

      {/* Persistent printer mark (visible without hover) */}
      {showPrintMark && isMarkedForPrint && !isHovering && (
        <div className="absolute top-2 left-2 p-1 rounded-full bg-black/40">
          <Printer className="w-3.5 h-3.5 text-white" />
        </div>
      )}

      {/* Hover overlay — desktop only. On touch it would sit on every tile
          permanently, and painting a gradient + icons + text per tile is the
          single biggest scroll cost on iOS (actions live in the viewer). */}
      {HOVER_CAPABLE && (
      <div
        className={clsx(
          "hover-overlay absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent",
          "transition-opacity duration-200"
        )}
      >
        {/* Actions, in the app-wide order: favorite, flag, print */}
        <div className="absolute top-2 right-2 flex gap-1">
          <button
            onClick={handleFavorite}
            disabled={isFavoriting}
            className="p-1 rounded-full hover:bg-white/20 transition-colors disabled:hover:bg-transparent"
          >
            {isFavoriting ? (
              <Loader2 className="w-5 h-5 animate-spin text-white" />
            ) : (
              <Star
                className={clsx(
                  "w-5 h-5",
                  isFavorite ? "fill-yellow-400 text-yellow-400" : "text-white"
                )}
              />
            )}
          </button>

          <button
            onClick={handleFlag}
            disabled={isFlagging}
            className="p-1 rounded-full hover:bg-white/20 transition-colors disabled:hover:bg-transparent"
            title={photo.flagged_for_removal ? "Unflag" : "Flag for removal"}
          >
            {isFlagging ? (
              <Loader2 className="w-5 h-5 animate-spin text-white" />
            ) : (
              <Flag
                className={clsx(
                  "w-5 h-5",
                  photo.flagged_for_removal ? "fill-red-400 text-red-400" : "text-white"
                )}
              />
            )}
          </button>

          {/* Photos only — videos can't be printed */}
          {!photo.is_video && (
            <button
              onClick={handlePrint}
              disabled={isPrinting}
              className="p-1 rounded-full hover:bg-white/20 transition-colors disabled:hover:bg-transparent"
              title={isMarkedForPrint ? "Remove from To Print" : "Add to To Print"}
            >
              {isPrinting ? (
                <Loader2 className="w-5 h-5 animate-spin text-white" />
              ) : (
                <Printer
                  className={clsx(
                    "w-5 h-5",
                    isMarkedForPrint ? "fill-sky-400 text-sky-400" : "text-white"
                  )}
                />
              )}
            </button>
          )}
        </div>

        {/* Live photo indicator */}
        {photo.has_live_photo && (
          <div className="absolute top-2 left-2">
            <Play className="w-4 h-4 text-white" />
          </div>
        )}

        {/* File name at bottom */}
        <div className="absolute bottom-0 left-0 right-0 px-2 py-1.5">
          <p className="text-white text-xs truncate">{photo.file_name}</p>
        </div>
      </div>
      )}
    </div>
  );
}
