import { useCallback, useState, useRef } from "react";
import { Star, Play } from "lucide-react";
import { clsx } from "clsx";
import type { PhotoSummary } from "../api/client";
import { api, thumbnailUrl, livePhotoUrl } from "../api/client";

interface PhotoGridProps {
  photos: PhotoSummary[];
  onPhotoClick: (photo: PhotoSummary, index: number) => void;
  onFavoriteToggle?: (photo: PhotoSummary) => void;
}

export function PhotoGrid({ photos, onPhotoClick, onFavoriteToggle }: PhotoGridProps) {
  if (photos.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <p>No photos found</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-1.5 p-4">
      {photos.map((photo, index) => (
        <PhotoGridItem
          key={photo.file_hash}
          photo={photo}
          onClick={() => onPhotoClick(photo, index)}
          onFavoriteToggle={onFavoriteToggle}
        />
      ))}
    </div>
  );
}

interface PhotoGridItemProps {
  photo: PhotoSummary;
  onClick: () => void;
  onFavoriteToggle?: (photo: PhotoSummary) => void;
}

function PhotoGridItem({ photo, onClick, onFavoriteToggle }: PhotoGridItemProps) {
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

  return (
    <div
      className="photo-grid-item aspect-square bg-gray-100"
      onClick={onClick}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <img
        src={thumbnailUrl(photo.file_hash, 200)}
        alt={photo.file_name}
        loading="lazy"
        className={clsx(
          "w-full h-full object-cover transition-opacity duration-200",
          isHovering && photo.has_live_photo && "opacity-0"
        )}
      />

      {/* Live Photo video overlay */}
      {photo.has_live_photo && (
        <video
          ref={videoRef}
          src={livePhotoUrl(photo.file_hash)}
          className={clsx(
            "absolute inset-0 w-full h-full object-cover",
            isHovering ? "opacity-100" : "opacity-0"
          )}
          muted
          loop
          playsInline
          preload="none"
        />
      )}

      {/* Hover overlay */}
      <div
        className={clsx(
          "absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent",
          "transition-opacity duration-200",
          isHovering ? "opacity-100" : "opacity-0"
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
