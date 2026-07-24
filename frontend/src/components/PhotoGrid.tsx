import { useCallback, useEffect, useState, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Star, Play, Printer, Flag, Grid2x2, Grid3x3, LayoutGrid, Crop, Expand } from "lucide-react";
import { clsx } from "clsx";
import type { PhotoSummary } from "../api/client";
import { api, thumbnailUrl, livePhotoUrl } from "../api/client";
import { useStore, type GridSize } from "../store/useStore";

const GRID_CLASSES: Record<GridSize, string> = {
  S: "grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10",
  M: "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6",
  L: "grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4",
};

const THUMB_SIZE: Record<GridSize, number> = { S: 300, M: 600, L: 600 };

interface PhotoGridProps {
  photos: PhotoSummary[];
  onPhotoClick: (photo: PhotoSummary, index: number) => void;
  onFavoriteToggle?: (photo: PhotoSummary) => void;
  onPrintToggle?: (photo: PhotoSummary) => void;
  /** Persistent printer mark on marked thumbnails (off on the To Print page itself). */
  showPrintMark?: boolean;
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
      <GridViewControls />
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
  const setStats = useStore((s) => s.setStats);
  const queryClient = useQueryClient();
  const gridFit = useStore((s) => s.gridFit);
  const fitClass = gridFit === "square" ? "object-cover" : "object-contain";
  const videoRef = useRef<HTMLVideoElement>(null);

  const handleFavorite = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      try {
        const result = await api.toggleFavorite(photo.file_hash);
        setIsFavorite(result.is_favorite);
        onFavoriteToggle?.(photo);
        // Single-user app: blanket invalidation is cheap and always correct.
        queryClient.invalidateQueries();
      } catch {
        // ignore
      }
    },
    [photo, onFavoriteToggle, queryClient]
  );

  const handlePrint = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      try {
        const result = await api.togglePrint(photo.file_hash);
        setIsMarkedForPrint(result.marked_for_print);
        onPrintToggle?.(photo);
        api.getStats().then(setStats).catch(() => {});
        queryClient.invalidateQueries();
      } catch {
        // ignore
      }
    },
    [photo, onPrintToggle, setStats, queryClient]
  );

  const handleFlag = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      try {
        await api.toggleFlag(photo.file_hash);
        // Flagged photos leave normal views; refetch removes the tile.
        api.getStats().then(setStats).catch(() => {});
        queryClient.invalidateQueries();
      } catch {
        // ignore
      }
    },
    [photo, setStats, queryClient]
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
        {/* Favorite button */}
        <button
          onClick={handleFavorite}
          className="absolute top-2 right-2 p-1 rounded-full hover:bg-white/20 transition-colors"
        >
          <Star
            className={clsx(
              "w-5 h-5",
              isFavorite ? "fill-yellow-400 text-yellow-400" : "text-white"
            )}
          />
        </button>

        {/* Print toggle (photos only — videos can't be printed) */}
        {!photo.is_video && (
          <button
            onClick={handlePrint}
            className="absolute top-2 right-9 p-1 rounded-full hover:bg-white/20 transition-colors"
            title={isMarkedForPrint ? "Remove from To Print" : "Add to To Print"}
          >
            <Printer
              className={clsx(
                "w-5 h-5",
                isMarkedForPrint ? "fill-sky-400 text-sky-400" : "text-white"
              )}
            />
          </button>
        )}

        {/* Flag for removal */}
        <button
          onClick={handleFlag}
          className="absolute top-2 right-16 p-1 rounded-full hover:bg-white/20 transition-colors"
          title={photo.flagged_for_removal ? "Unflag" : "Flag for removal"}
        >
          <Flag
            className={clsx(
              "w-5 h-5",
              photo.flagged_for_removal ? "fill-red-400 text-red-400" : "text-white"
            )}
          />
        </button>

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
