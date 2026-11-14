import { memo, useCallback, useEffect, useRef, useState } from "react";
import { Flag, Loader2, Play, Printer, Star } from "lucide-react";
import { clsx } from "clsx";
import { livePhotoUrl, thumbnailUrl, type PhotoSummary } from "../api/client";
import { usePhotoActions } from "../hooks/usePhotoActions";
import { formatDuration } from "../lib/format";
import { useStore, type GridFit, type GridSize } from "../store/useStore";
import { GridViewControls } from "./GridViewControls";

const GRID_CLASSES: Record<GridSize, string> = {
  S: "grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10",
  M: "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6",
  L: "grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-3 xl:grid-cols-4",
};

// Exported so the viewer can reuse the exact URL the grid already fetched:
// that cache hit is what makes its placeholder appear with no network wait.
export const THUMB_SIZE: Record<GridSize, number> = { S: 300, M: 600, L: 600 };

/** Opens a photo from a list; the list is what the viewer steps through. */
export type OpenPhoto = (photo: PhotoSummary, index: number, list: PhotoSummary[]) => void;

interface PhotoGridProps {
  photos: PhotoSummary[];
  onPhotoClick: OpenPhoto;
  /** Render the floating size/fit controls. Set false when a page shows many
   *  grids (month groups) and renders GridViewControls once itself. */
  showControls?: boolean;
}

/** Touch devices never hover, so live-photo <video> elements would be dead
 *  weight there: iOS Safari slows to a crawl with many media elements. */
const HOVER_CAPABLE =
  typeof window !== "undefined" &&
  window.matchMedia("(hover: hover) and (pointer: fine)").matches;

export function PhotoGrid({ photos, onPhotoClick, showControls = true }: PhotoGridProps) {
  const gridSize = useStore((s) => s.gridSize);
  const gridFit = useStore((s) => s.gridFit);

  // Stable per list, so a tile only re-renders when its own photo changes:
  // after a toggle the refetched list keeps every untouched photo object.
  const open = useCallback(
    (photo: PhotoSummary, index: number) => onPhotoClick(photo, index, photos),
    [onPhotoClick, photos]
  );

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
          <PhotoTile
            key={photo.file_hash}
            photo={photo}
            index={index}
            onOpen={open}
            thumbSize={THUMB_SIZE[gridSize]}
            fit={gridFit}
          />
        ))}
      </div>
      {showControls && <GridViewControls />}
    </>
  );
}

/**
 * A boolean that follows its prop, but can be set locally in between: the
 * tile shows a toggle's answer the moment the POST returns, and the refetched
 * list (or a toggle made in the viewer) still wins once it lands.
 */
function useFollowingState(prop: boolean) {
  const [value, setValue] = useState(prop);
  const [seen, setSeen] = useState(prop);
  if (prop !== seen) {
    setSeen(prop);
    setValue(prop);
  }
  return [value, setValue] as const;
}

type TileAction = "favorite" | "flag" | "print";
const IDLE: Record<TileAction, boolean> = { favorite: false, flag: false, print: false };

interface PhotoTileProps {
  photo: PhotoSummary;
  index: number;
  onOpen: (photo: PhotoSummary, index: number) => void;
  thumbSize: number;
  fit: GridFit;
}

const PhotoTile = memo(function PhotoTile({ photo, index, onOpen, thumbSize, fit }: PhotoTileProps) {
  const actions = usePhotoActions();
  const [isHovering, setIsHovering] = useState(false);
  const [everHovered, setEverHovered] = useState(false);
  const [videoFailed, setVideoFailed] = useState(false);
  const [isFavorite, setIsFavorite] = useFollowingState(photo.is_favorite);
  const [isMarkedForPrint, setIsMarkedForPrint] = useFollowingState(photo.marked_for_print);
  // Per action, so e.g. favoriting still works while a flag is in flight.
  const [pending, setPending] = useState<Record<TileAction, boolean>>(IDLE);
  const videoRef = useRef<HTMLVideoElement>(null);
  const fitClass = fit === "square" ? "object-cover" : "object-contain";

  const run = async (kind: TileAction, e: React.MouseEvent, action: () => Promise<void>) => {
    e.stopPropagation();
    if (pending[kind]) return;
    setPending((p) => ({ ...p, [kind]: true }));
    try {
      await action();
    } catch {
      // The tile simply keeps its previous state.
    } finally {
      setPending((p) => ({ ...p, [kind]: false }));
    }
  };

  // The tile stays put on favorite and print, so the spinner only covers the
  // POST: the filled icon is the acknowledgement from the moment it lands.
  const handleFavorite = (e: React.MouseEvent) =>
    run("favorite", e, async () => {
      setIsFavorite((await actions.toggleFavorite(photo.file_hash)).value);
    });

  const handlePrint = (e: React.MouseEvent) =>
    run("print", e, async () => {
      setIsMarkedForPrint((await actions.togglePrint(photo.file_hash)).value);
    });

  // A flagged photo leaves the list, but only once the refetch lands, a beat
  // or two after the click. Spin for that whole window, or the tile looks
  // unresponsive in between.
  const handleFlag = (e: React.MouseEvent) =>
    run("flag", e, async () => {
      await (await actions.toggleFlag(photo.file_hash)).refreshed;
    });

  const showVideo = isHovering && photo.has_live_photo && !videoFailed;
  // Mount the video lazily on first hover; keep it mounted afterwards so
  // re-hovering doesn't re-fetch.
  const mountVideo = HOVER_CAPABLE && everHovered && photo.has_live_photo && !videoFailed;

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
      onClick={() => onOpen(photo, index)}
      onMouseEnter={() => {
        setIsHovering(true);
        setEverHovered(true);
      }}
      onMouseLeave={() => setIsHovering(false)}
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
      {isMarkedForPrint && !isHovering && (
        <div className="absolute top-2 left-2 p-1 rounded-full bg-black/40">
          <Printer className="w-3.5 h-3.5 text-white" />
        </div>
      )}

      {/* Hover overlay, desktop only. On touch it would sit on every tile
          permanently, and painting a gradient + icons + text per tile is the
          single biggest scroll cost on iOS (actions live in the viewer). */}
      {HOVER_CAPABLE && (
        <div className="hover-overlay absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent transition-opacity duration-200">
          {/* Actions, in the app-wide order: favorite, flag, print */}
          <div className="absolute top-2 right-2 flex gap-1">
            <TileButton busy={pending.favorite} onClick={handleFavorite}>
              <Star className={clsx("w-5 h-5", isFavorite ? "fill-yellow-400 text-yellow-400" : "text-white")} />
            </TileButton>

            <TileButton
              busy={pending.flag}
              onClick={handleFlag}
              title={photo.flagged_for_removal ? "Unflag" : "Flag for removal"}
            >
              <Flag
                className={clsx(
                  "w-5 h-5",
                  photo.flagged_for_removal ? "fill-red-400 text-red-400" : "text-white"
                )}
              />
            </TileButton>

            {/* Photos only: videos can't be printed */}
            {!photo.is_video && (
              <TileButton
                busy={pending.print}
                onClick={handlePrint}
                title={isMarkedForPrint ? "Remove from To Print" : "Add to To Print"}
              >
                <Printer
                  className={clsx("w-5 h-5", isMarkedForPrint ? "fill-sky-400 text-sky-400" : "text-white")}
                />
              </TileButton>
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
});

function TileButton({
  busy,
  onClick,
  title,
  children,
}: {
  busy: boolean;
  onClick: (e: React.MouseEvent) => void;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="p-1 rounded-full hover:bg-white/20 transition-colors disabled:hover:bg-transparent"
      title={title}
    >
      {busy ? <Loader2 className="w-5 h-5 animate-spin text-white" /> : children}
    </button>
  );
}
