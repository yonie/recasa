import { useCallback, useState, useRef } from "react";
import { Star, Play, Grid2x2, Grid3x3, LayoutGrid } from "lucide-react";
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
}

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
      className="w-10 h-10 rounded-full bg-white/90 backdrop-blur-sm shadow-lg
                 border border-gray-200 flex items-center justify-center
                 hover:bg-gray-100 transition-colors"
      title={`Grid size: ${gridSize}`}
    >
      <Icon className="w-5 h-5 text-gray-600" />
    </button>
  );
}

export function PhotoGrid({ photos, onPhotoClick, onFavoriteToggle }: PhotoGridProps) {
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
      <div className={clsx("grid gap-1.5 p-4", GRID_CLASSES[gridSize])}>
        {photos.map((photo, index) => (
          <PhotoGridItem
            key={photo.file_hash}
            photo={photo}
            onClick={() => onPhotoClick(photo, index)}
            onFavoriteToggle={onFavoriteToggle}
            thumbSize={THUMB_SIZE[gridSize]}
          />
        ))}
      </div>
      <div className="fixed bottom-4 right-4 z-30">
        <GridSizeToggle />
      </div>
    </>
  );
}

interface PhotoGridItemProps {
  photo: PhotoSummary;
  onClick: () => void;
  onFavoriteToggle?: (photo: PhotoSummary) => void;
  thumbSize: number;
}

function PhotoGridItem({ photo, onClick, onFavoriteToggle, thumbSize }: PhotoGridItemProps) {
  const [isHovering, setIsHovering] = useState(false);
  const [isFavorite, setIsFavorite] = useState(photo.is_favorite);
  const videoRef = useRef<HTMLVideoElement>(null);

  const handleFavorite = useCallback(
    async (e: React.MouseEvent) => {
      e.stopPropagation();
      try {
        const result = await api.toggleFavorite(photo.file_hash);
        setIsFavorite(result.is_favorite);
        onFavoriteToggle?.(photo);
      } catch {
        // ignore
      }
    },
    [photo, onFavoriteToggle]
  );

  const handleMouseEnter = useCallback(() => {
    setIsHovering(true);
    if (photo.has_live_photo && videoRef.current) {
      videoRef.current.play().catch(() => {});
    }
  }, [photo.has_live_photo]);

  const handleMouseLeave = useCallback(() => {
    setIsHovering(false);
    if (videoRef.current) {
      videoRef.current.pause();
      videoRef.current.currentTime = 0;
    }
  }, []);

  const [videoFailed, setVideoFailed] = useState(false);
  const showVideo = isHovering && photo.has_live_photo && !videoFailed;

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
        className={clsx(
          "w-full h-full object-cover transition-opacity duration-200",
          showVideo && "opacity-0"
        )}
      />

      {/* Live Photo video overlay */}
      {photo.has_live_photo && (
        <video
          ref={videoRef}
          src={livePhotoUrl(photo.file_hash)}
          className={clsx(
            "absolute inset-0 w-full h-full object-cover",
            showVideo ? "opacity-100" : "opacity-0"
          )}
          muted
          loop
          playsInline
          preload="none"
          onError={() => setVideoFailed(true)}
        />
      )}

      {/* Hover overlay */}
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
    </div>
  );
}
