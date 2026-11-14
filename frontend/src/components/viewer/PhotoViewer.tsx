import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, Flag, Info, Printer, Star, X } from "lucide-react";
import { clsx } from "clsx";
import { useQueryClient } from "@tanstack/react-query";
import { api, fullViewUrl, thumbnailUrl, videoUrl } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import { bestDetail, fetchPhotoDetail } from "../../hooks/useOpenPhoto";
import { usePhotoActions } from "../../hooks/usePhotoActions";
import { useStore } from "../../store/useStore";
import { gridThumbSize } from "../../lib/gridLayout";
import { usePhotoGestures } from "./usePhotoGestures";
import { useViewerHistory } from "./useViewerHistory";
import { ViewerInfoPanel } from "./ViewerInfoPanel";

type Mark = "is_favorite" | "marked_for_print" | "flagged_for_removal";

/**
 * Toggle results for the photo on screen. They outrank the photo's own fields
 * until the user moves on: a detail response that was already in flight when
 * F was pressed must not flip the star back.
 */
interface Overrides {
  hash: string;
  marks: Partial<Record<Mark, boolean>>;
}

export function PhotoViewer() {
  const viewerPhoto = useStore((s) => s.viewerPhoto);
  const viewerOpen = useStore((s) => s.viewerOpen);
  const viewerPhotoList = useStore((s) => s.viewerPhotoList);
  const viewerIndex = useStore((s) => s.viewerIndex);
  const closeViewer = useStore((s) => s.closeViewer);
  const setViewerPhoto = useStore((s) => s.setViewerPhoto);
  const setViewerIndex = useStore((s) => s.setViewerIndex);
  const gridSize = useStore((s) => s.gridSize);
  const actions = usePhotoActions();
  const queryClient = useQueryClient();

  const [showInfo, setShowInfo] = useState(false);
  const [overrides, setOverrides] = useState<Overrides | null>(null);
  // Hash of the photo whose full view has finished decoding. Until it matches,
  // the thumbnail placeholder stays visible underneath.
  const [fullLoaded, setFullLoaded] = useState<string | null>(null);

  const detail = viewerPhoto;
  const mark = (key: Mark): boolean =>
    (overrides?.hash === detail?.file_hash ? overrides?.marks[key] : undefined) ?? detail?.[key] ?? false;

  const canNavigate = viewerPhotoList.length > 0 && viewerIndex >= 0;
  const canGoPrev = canNavigate && viewerIndex > 0;
  const canGoNext = canNavigate && viewerIndex < viewerPhotoList.length - 1;

  const navigateTo = useCallback(
    (newIndex: number) => {
      const photo = viewerPhotoList[newIndex];
      if (!photo) return;

      // Switch photos synchronously from what we already have: the prefetched
      // detail, or else the list entry. Awaiting the detail fetch first is
      // what used to leave the previous photo on screen for a round-trip.
      setViewerPhoto(bestDetail(queryClient, photo));
      setViewerIndex(newIndex);
      window.history.replaceState({ viewerOpen: true }, "", `/photos/${photo.file_hash}`);

      fetchPhotoDetail(queryClient, photo.file_hash)
        .then((fullDetail) => {
          // Drop a response that lost the race to a newer navigation.
          if (useStore.getState().viewerPhoto?.file_hash === fullDetail.file_hash) {
            setViewerPhoto(fullDetail);
          }
        })
        .catch(() => {});
    },
    [queryClient, viewerPhotoList, setViewerPhoto, setViewerIndex]
  );

  const goPrev = () => canGoPrev && navigateTo(viewerIndex - 1);
  const goNext = () => canGoNext && navigateTo(viewerIndex + 1);

  const toggle = async (key: Mark, run: (hash: string) => Promise<{ value: boolean }>) => {
    if (!detail) return;
    const hash = detail.file_hash;
    try {
      const { value } = await run(hash);
      setOverrides((prev) => ({
        hash,
        marks: { ...(prev?.hash === hash ? prev.marks : {}), [key]: value },
      }));
    } catch {
      // The button keeps showing the previous state.
    }
  };
  const handleFavorite = () => toggle("is_favorite", actions.toggleFavorite);
  const handlePrint = () => toggle("marked_for_print", actions.togglePrint);
  const handleFlag = () => toggle("flagged_for_removal", actions.toggleFlag);

  const gestures = usePhotoGestures({
    resetKey: detail?.file_hash ?? "",
    onSwipeLeft: goNext,
    onSwipeRight: goPrev,
  });

  useViewerHistory(viewerOpen, closeViewer);

  // Keyboard shortcuts while open. The listener reads the latest handler
  // through a ref, so it is bound once per opening rather than per render.
  const onKey = useRef<(e: KeyboardEvent) => void>(() => {});
  useLayoutEffect(() => {
    onKey.current = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        closeViewer();
      }
      if (e.key === "i") setShowInfo((s) => !s);
      if (e.key === "ArrowLeft") goPrev();
      if (e.key === "ArrowRight") goNext();
      if (e.key === "f" || e.key === "s") void handleFavorite();
      if (e.key === "p") void handlePrint();
      if (e.key === "r") void handleFlag();
    };
  });
  useEffect(() => {
    if (!viewerOpen) return;
    const listener = (e: KeyboardEvent) => onKey.current(e);
    document.addEventListener("keydown", listener);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", listener);
      document.body.style.overflow = "";
    };
  }, [viewerOpen]);

  // Warm the next/previous full views (and, for RAW and HEIC, the server-side
  // render cache) and their details, so a step shows the photo and its info
  // at once instead of waiting on a decode and a request. Started once the
  // photo on screen has decoded, so the neighbours (often several MB each)
  // don't compete with it for the Pi's bandwidth; a slow one is not waited
  // on for more than a moment.
  const currentReady = !!detail && (detail.is_video || fullLoaded === detail.file_hash);
  useEffect(() => {
    if (!viewerOpen || viewerIndex < 0) return;
    const t = setTimeout(
      () => {
        for (const i of [viewerIndex + 1, viewerIndex - 1]) {
          const p = viewerPhotoList[i];
          if (!p) continue;
          if (!p.is_video) new Image().src = fullViewUrl(p);
          void queryClient.prefetchQuery({
            queryKey: queryKeys.photo(p.file_hash),
            queryFn: () => api.getPhoto(p.file_hash),
          });
        }
      },
      currentReady ? 0 : 1500
    );
    return () => clearTimeout(t);
  }, [queryClient, viewerOpen, viewerIndex, viewerPhotoList, currentReady]);

  // An image served from cache can finish before React attaches onLoad, which
  // would leave the placeholder up over a ready image.
  useEffect(() => {
    const el = gestures.imgRef.current;
    if (detail && el?.complete && el.naturalWidth > 0) setFullLoaded(detail.file_hash);
  }, [detail, gestures.imgRef]);

  if (!viewerOpen || !detail) return null;

  const stop = (fn: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation();
    fn();
  };

  return (
    <div className="fixed inset-0 z-[2000] bg-black/95 flex flex-col sm:flex-row pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
      {/* Main image */}
      <div
        ref={gestures.containerRef}
        className="flex-1 flex items-center justify-center relative touch-none"
        /* The grid's own thumbnail, already in the browser cache, stands in
           until the full view decodes. Letterboxed the same way the image is,
           so the swap lands in place. */
        style={
          !detail.is_video && fullLoaded !== detail.file_hash
            ? {
                // Same size the grid chose, so this is a browser-cache hit.
                backgroundImage: `url("${thumbnailUrl(detail.file_hash, gridThumbSize(gridSize))}")`,
                backgroundSize: "contain",
                backgroundPosition: "center",
                backgroundRepeat: "no-repeat",
              }
            : undefined
        }
        onClick={closeViewer}
        onTouchStart={gestures.onTouchStart}
        onTouchMove={gestures.onTouchMove}
        onTouchEnd={gestures.onTouchEnd}
      >
        {detail.is_video ? (
          <div className="flex flex-col items-center gap-3" onClick={(e) => e.stopPropagation()}>
            <video
              src={videoUrl(detail.file_hash)}
              className="max-w-full max-h-[85vh] object-contain"
              controls
              autoPlay
              playsInline
            />
            {/* Old codecs (MPEG-4 Part 2, MJPEG) can't decode in-browser:
                offer the original so the video is still retrievable. */}
            <a
              href={videoUrl(detail.file_hash)}
              download={detail.file_name}
              className="text-xs text-white/60 hover:text-white/90 underline"
            >
              Video won't play? Download the original
            </a>
          </div>
        ) : (
          <img
            /* Keyed so each photo gets a fresh element: a reused <img> keeps
               painting the previous photo until the new bytes decode. */
            key={detail.file_hash}
            ref={gestures.imgRef}
            data-testid="full-view"
            src={fullViewUrl(detail)}
            alt={detail.file_name}
            className={clsx(
              "max-w-full max-h-full object-contain transition-opacity duration-200",
              fullLoaded === detail.file_hash ? "opacity-100" : "opacity-0"
            )}
            onLoad={() => setFullLoaded(detail.file_hash)}
            onClick={(e) => e.stopPropagation()}
          />
        )}

        {/* Top toolbar */}
        <div className="absolute top-0 left-0 right-0 flex items-center justify-between p-4 pt-[calc(1rem+env(safe-area-inset-top))]">
          <ToolbarButton onClick={closeViewer}>
            <X className="w-5 h-5" />
          </ToolbarButton>

          <div className="flex items-center gap-2">
            {canNavigate && (
              <span className="text-white/60 text-sm mr-2">
                {viewerIndex + 1} / {viewerPhotoList.length}
              </span>
            )}
            <ToolbarButton onClick={stop(handleFavorite)} title="Favorite (F)">
              <Star className={clsx("w-5 h-5", mark("is_favorite") && "fill-yellow-400 text-yellow-400")} />
            </ToolbarButton>
            <ToolbarButton onClick={stop(handleFlag)} title="Flag for removal (R)">
              <Flag className={clsx("w-5 h-5", mark("flagged_for_removal") && "fill-red-400 text-red-400")} />
            </ToolbarButton>
            <ToolbarButton onClick={stop(handlePrint)} title="To Print (P)">
              <Printer className={clsx("w-5 h-5", mark("marked_for_print") && "fill-sky-400 text-sky-400")} />
            </ToolbarButton>
            <button
              onClick={stop(() => setShowInfo((s) => !s))}
              className={clsx(
                "p-2 rounded-full transition-colors",
                showInfo ? "bg-white/20 text-white" : "bg-black/40 active:bg-black/60 text-white"
              )}
              title="Info (I)"
            >
              <Info className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Navigation arrows */}
        {canGoPrev && (
          <NavArrow side="left" onClick={stop(goPrev)}>
            <ChevronLeft className="w-6 h-6" />
          </NavArrow>
        )}
        {canGoNext && (
          <NavArrow side="right" onClick={stop(goNext)}>
            <ChevronRight className="w-6 h-6" />
          </NavArrow>
        )}

        {/* Caption overlay at bottom */}
        {detail.caption && !showInfo && (
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent px-6 py-4 pointer-events-none">
            <p className="text-white/90 text-sm italic max-w-2xl">{detail.caption}</p>
          </div>
        )}
      </div>

      {showInfo && <ViewerInfoPanel detail={detail} />}
    </div>
  );
}

function ToolbarButton({
  onClick,
  title,
  children,
}: {
  onClick: (e: React.MouseEvent) => void;
  title?: string;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="p-2 rounded-full bg-black/40 active:bg-black/60 text-white transition-colors"
      title={title}
    >
      {children}
    </button>
  );
}

function NavArrow({
  side,
  onClick,
  children,
}: {
  side: "left" | "right";
  onClick: (e: React.MouseEvent) => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={clsx(
        "absolute top-1/2 -translate-y-1/2 p-3 sm:p-2 rounded-full bg-black/40 active:bg-black/60 text-white transition-colors",
        side === "left" ? "left-2 sm:left-4" : "right-2 sm:right-4"
      )}
    >
      {children}
    </button>
  );
}
