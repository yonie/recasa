import { useEffect, useLayoutEffect, useCallback, useState, useRef } from "react";
import {
  X,
  Star,
  Printer,
  MapPin,
  Camera,
  Clock,
  HardDrive,
  Info,
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  Users,
  Tag,
} from "lucide-react";
import { clsx } from "clsx";
import { useQueryClient } from "@tanstack/react-query";
import { useStore } from "../store/useStore";
import { api, originalUrl, type PhotoDetail } from "../api/client";

export function PhotoViewer() {
  const {
    viewerPhoto,
    viewerOpen,
    closeViewer,
    viewerPhotoList,
    viewerIndex,
    setViewerPhoto,
    setViewerIndex,
  } = useStore();
  
  const historyPushed = useRef(false);
  const [detail, setDetail] = useState<PhotoDetail | null>(null);
  const [showInfo, setShowInfo] = useState(false);
  const [isFavorite, setIsFavorite] = useState(false);
  const [isMarkedForPrint, setIsMarkedForPrint] = useState(false);
  const [loading, setLoading] = useState(false);
  const setStats = useStore((s) => s.setStats);
  const queryClient = useQueryClient();

  const gestures = usePhotoGestures({
    resetKey: viewerPhoto?.file_hash ?? "",
    onSwipeLeft: () => {
      if (canGoNext) navigateTo(viewerIndex + 1);
    },
    onSwipeRight: () => {
      if (canGoPrev) navigateTo(viewerIndex - 1);
    },
  });

  useEffect(() => {
    if (viewerPhoto) {
      setDetail(viewerPhoto);
      setIsFavorite(viewerPhoto.is_favorite);
      setIsMarkedForPrint(viewerPhoto.marked_for_print);
    }
  }, [viewerPhoto]);

  const canNavigate = viewerPhotoList.length > 0 && viewerIndex >= 0;
  const canGoPrev = canNavigate && viewerIndex > 0;
  const canGoNext = canNavigate && viewerIndex < viewerPhotoList.length - 1;

  const navigateTo = useCallback(
    async (newIndex: number) => {
      if (newIndex < 0 || newIndex >= viewerPhotoList.length || loading) return;

      const photo = viewerPhotoList[newIndex];
      if (!photo) return;

      setLoading(true);
      try {
        const fullDetail = await api.getPhoto(photo.file_hash);
        setViewerPhoto(fullDetail);
        setViewerIndex(newIndex);
        // Update URL to reflect current photo
        window.history.replaceState({ viewerOpen: true }, "", `/photos/${photo.file_hash}`);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    },
    [viewerPhotoList, loading, setViewerPhoto, setViewerIndex]
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopImmediatePropagation(); closeViewer(); }
      if (e.key === "i") setShowInfo((s) => !s);
      if (e.key === "ArrowLeft" && canGoPrev) navigateTo(viewerIndex - 1);
      if (e.key === "ArrowRight" && canGoNext) navigateTo(viewerIndex + 1);
      if (e.key === "f" || e.key === "s") {
        // Star/favorite toggle
        if (detail) handleFavorite();
      }
      if (e.key === "p") {
        // To Print toggle
        if (detail) handlePrint();
      }
    },
    [closeViewer, canGoPrev, canGoNext, viewerIndex, navigateTo, detail]
  );

  // Track the URL we had before opening the viewer
  const previousUrl = useRef<string | null>(null);

  // Handle browser back button to close viewer
  useEffect(() => {
    if (viewerOpen) {
      // Push a history state when opening viewer
      if (!historyPushed.current) {
        // Save the current URL before changing it
        previousUrl.current = window.location.pathname + window.location.search;
        // Use viewerPhoto (store state, already current) instead of detail (local state, stale until next render)
        window.history.pushState({ viewerOpen: true }, "", `/photos/${viewerPhoto?.file_hash || ""}`);
        historyPushed.current = true;
      }
      
      document.addEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "hidden";
      
      // Handle back button
      const handlePopState = () => {
        if (historyPushed.current) {
          closeViewer();
          historyPushed.current = false;
        }
      };
      
      window.addEventListener("popstate", handlePopState);
      
      return () => {
        document.removeEventListener("keydown", handleKeyDown);
        document.body.style.overflow = "";
        window.removeEventListener("popstate", handlePopState);
      };
    } else {
      // When viewer closes, restore the previous URL
      if (historyPushed.current && previousUrl.current) {
        window.history.replaceState(null, "", previousUrl.current);
        previousUrl.current = null;
      }
      historyPushed.current = false;
    }
  }, [viewerOpen, viewerPhoto, handleKeyDown, closeViewer]);

  const handleFavorite = useCallback(async () => {
    if (!detail) return;
    try {
      const result = await api.toggleFavorite(detail.file_hash);
      setIsFavorite(result.is_favorite);
      queryClient.invalidateQueries();
    } catch {
      // ignore
    }
  }, [detail, queryClient]);

  const handlePrint = useCallback(async () => {
    if (!detail) return;
    try {
      const result = await api.togglePrint(detail.file_hash);
      setIsMarkedForPrint(result.marked_for_print);
      api.getStats().then(setStats).catch(() => {});
      queryClient.invalidateQueries();
    } catch {
      // ignore
    }
  }, [detail, setStats, queryClient]);

  if (!viewerOpen || !detail) return null;

  return (
    <div className="fixed inset-0 z-[2000] bg-black/95 flex flex-col sm:flex-row pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">
      {/* Main image */}
      <div
        ref={gestures.containerRef}
        className="flex-1 flex items-center justify-center relative touch-none"
        onClick={closeViewer}
        onTouchStart={gestures.onTouchStart}
        onTouchMove={gestures.onTouchMove}
        onTouchEnd={gestures.onTouchEnd}
      >
        <img
          ref={gestures.imgRef}
          src={originalUrl(detail.file_hash)}
          alt={detail.file_name}
          className={clsx(
            "max-w-full max-h-full object-contain transition-opacity duration-200",
            loading && "opacity-50"
          )}
          onClick={(e) => e.stopPropagation()}
        />

        {/* Top toolbar */}
        <div className="absolute top-0 left-0 right-0 flex items-center justify-between p-4 pt-[calc(1rem+env(safe-area-inset-top))]">
          <button
            onClick={closeViewer}
            className="p-2 rounded-full bg-black/40 active:bg-black/60 text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>

          <div className="flex items-center gap-2">
            {canNavigate && (
              <span className="text-white/60 text-sm mr-2">
                {viewerIndex + 1} / {viewerPhotoList.length}
              </span>
            )}
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleFavorite();
              }}
              className="p-2 rounded-full bg-black/40 active:bg-black/60 text-white transition-colors"
              title="Favorite (F)"
            >
              <Star
                className={clsx(
                  "w-5 h-5",
                  isFavorite && "fill-yellow-400 text-yellow-400"
                )}
              />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                handlePrint();
              }}
              className="p-2 rounded-full bg-black/40 active:bg-black/60 text-white transition-colors"
              title="To Print (P)"
            >
              <Printer
                className={clsx(
                  "w-5 h-5",
                  isMarkedForPrint && "fill-sky-400 text-sky-400"
                )}
              />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                setShowInfo((s) => !s);
              }}
              className={clsx(
                "p-2 rounded-full transition-colors",
                showInfo
                  ? "bg-white/20 text-white"
                  : "bg-black/40 active:bg-black/60 text-white"
              )}
              title="Info (I)"
            >
              <Info className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Navigation arrows */}
        {canGoPrev && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              navigateTo(viewerIndex - 1);
            }}
            className="absolute left-2 sm:left-4 top-1/2 -translate-y-1/2 p-3 sm:p-2 rounded-full bg-black/40 active:bg-black/60 text-white transition-colors"
          >
            <ChevronLeft className="w-6 h-6" />
          </button>
        )}
        {canGoNext && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              navigateTo(viewerIndex + 1);
            }}
            className="absolute right-2 sm:right-4 top-1/2 -translate-y-1/2 p-3 sm:p-2 rounded-full bg-black/40 active:bg-black/60 text-white transition-colors"
          >
            <ChevronRight className="w-6 h-6" />
          </button>
        )}

        {/* Caption overlay at bottom */}
        {detail.caption && !showInfo && (
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent px-6 py-4 pointer-events-none">
            <p className="text-white/90 text-sm italic max-w-2xl">{detail.caption}</p>
          </div>
        )}
      </div>

      {/* Info panel */}
      {showInfo && (
        <div className="w-full sm:w-80 bg-gray-900 text-white overflow-y-auto border-t sm:border-t-0 sm:border-l border-gray-700 fixed sm:relative bottom-0 left-0 right-0 max-h-[50vh] sm:max-h-full">
          <div className="p-4 space-y-6">
            {/* File info */}
            <section>
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
                File
              </h3>
              <p className="text-sm font-medium break-all">{detail.file_name}</p>
              <p className="text-xs text-gray-400 mt-1">{detail.file_path}</p>
              {detail.width && detail.height && (
                <p className="text-xs text-gray-400">
                  {detail.width} x {detail.height}
                </p>
              )}
              <p className="text-xs text-gray-400">
                <HardDrive className="w-3 h-3 inline mr-1" />
                {formatBytes(detail.file_size)}
              </p>
            </section>

            {/* Date */}
            {detail.date_taken && (
              <section>
                <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  Date
                </h3>
                <p className="text-sm flex items-center gap-2">
                  <Clock className="w-4 h-4 text-gray-400" />
                  {new Date(detail.date_taken).toLocaleString()}
                </p>
              </section>
            )}

            {/* Location */}
            {detail.location && (
              <section>
                <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  Location
                </h3>
                <p className="text-sm flex items-center gap-2">
                  <MapPin className="w-4 h-4 text-gray-400" />
                  {detail.location.address || `${detail.location.city}, ${detail.location.country}`}
                </p>
                {detail.location.latitude && detail.location.longitude && (
                  <p className="text-xs text-gray-400 mt-1">
                    {detail.location.latitude.toFixed(6)}, {detail.location.longitude.toFixed(6)}
                  </p>
                )}
              </section>
            )}

            {/* Camera / EXIF */}
            {detail.exif && (detail.exif.camera_make || detail.exif.camera_model) && (
              <section>
                <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
                  Camera
                </h3>
                <p className="text-sm flex items-center gap-2">
                  <Camera className="w-4 h-4 text-gray-400" />
                  {[detail.exif.camera_make, detail.exif.camera_model]
                    .filter(Boolean)
                    .join(" ")}
                </p>
                {detail.exif.lens_model && (
                  <p className="text-xs text-gray-400 mt-1">{detail.exif.lens_model}</p>
                )}
                <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-gray-400">
                  {detail.exif.focal_length && (
                    <span>{detail.exif.focal_length}mm</span>
                  )}
                  {detail.exif.aperture && <span>f/{detail.exif.aperture}</span>}
                  {detail.exif.shutter_speed && (
                    <span>{detail.exif.shutter_speed}s</span>
                  )}
                  {detail.exif.iso && <span>ISO {detail.exif.iso}</span>}
                </div>
              </section>
            )}

            {/* Caption */}
            {detail.caption && (
              <section>
                <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2 flex items-center gap-1.5">
                  <MessageSquare className="w-3.5 h-3.5" />
                  AI Caption
                </h3>
                <p className="text-sm text-gray-300 italic">{detail.caption}</p>
              </section>
            )}

            {/* Tags */}
            {detail.tags && detail.tags.length > 0 && (
              <section>
                <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2 flex items-center gap-2">
                  <Tag className="w-3.5 h-3.5" />
                  Tags
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {detail.tags.map((t) => {
                    const color = getTagColor(t.name);
                    return (
                      <span
                        key={t.tag_id}
                        className="px-2 py-0.5 rounded-full text-xs"
                        style={{
                          backgroundColor: color.bg,
                          color: color.text,
                        }}
                      >
                        {t.name}
                      </span>
                    );
                  })}
                </div>
              </section>
            )}

            {/* Faces */}
            {detail.faces.length > 0 && (
              <section>
                <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2 flex items-center gap-1.5">
                  <Users className="w-3.5 h-3.5" />
                  People ({detail.faces.length})
                </h3>
                <div className="space-y-1">
                  {detail.faces.map((face) => (
                    <div key={face.face_id} className="text-sm text-gray-300">
                      {face.person_name || `Person ${face.person_id || "?"}`}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Keyboard shortcuts */}
            <section>
              <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
                Shortcuts
              </h3>
              <div className="grid grid-cols-2 gap-1 text-xs text-gray-500">
                <span className="font-mono bg-gray-800 px-1.5 py-0.5 rounded text-center">Esc</span>
                <span>Close</span>
                <span className="font-mono bg-gray-800 px-1.5 py-0.5 rounded text-center">I</span>
                <span>Toggle info</span>
                <span className="font-mono bg-gray-800 px-1.5 py-0.5 rounded text-center">F</span>
                <span>Favorite</span>
                <span className="font-mono bg-gray-800 px-1.5 py-0.5 rounded text-center">P</span>
                <span>To Print</span>
                <span className="font-mono bg-gray-800 px-1.5 py-0.5 rounded text-center">&larr; &rarr;</span>
                <span>Navigate</span>
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}

const MAX_SCALE = 5;
const DOUBLE_TAP_SCALE = 2.5;

/**
 * Pinch-to-zoom, pan, double-tap zoom and swipe navigation for the viewer
 * image. Writes transforms directly to the element (no React state per
 * touchmove) so gestures stay at native frame rate. Swipe callbacks only
 * fire when not zoomed in; while zoomed, one finger pans instead.
 */
function usePhotoGestures({
  resetKey,
  onSwipeLeft,
  onSwipeRight,
}: {
  resetKey: string;
  onSwipeLeft: () => void;
  onSwipeRight: () => void;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const t = useRef({ scale: 1, tx: 0, ty: 0 });
  const pinch = useRef<{ dist: number; mx: number; my: number } | null>(null);
  const pan = useRef<{ x: number; y: number; startX: number; startY: number } | null>(null);
  const swipe = useRef<{ x: number; y: number } | null>(null);
  const lastTap = useRef({ time: 0, x: 0, y: 0 });

  const apply = useCallback((animate: boolean) => {
    const img = imgRef.current;
    if (!img) return;
    img.style.transition = animate
      ? "transform 0.25s ease, opacity 0.2s"
      : "opacity 0.2s";
    const { scale, tx, ty } = t.current;
    img.style.transform =
      scale === 1 && tx === 0 && ty === 0
        ? ""
        : `translate3d(${tx}px, ${ty}px, 0) scale(${scale})`;
  }, []);

  const reset = useCallback(
    (animate: boolean) => {
      t.current = { scale: 1, tx: 0, ty: 0 };
      pinch.current = null;
      pan.current = null;
      apply(animate);
    },
    [apply]
  );

  // New photo: clear any zoom before it paints
  useLayoutEffect(() => {
    reset(false);
  }, [resetKey, reset]);

  // Keep the pan within the scaled image's bounds (image is flex-centered,
  // so its untransformed center coincides with the container center)
  const clampPan = () => {
    const img = imgRef.current;
    const c = containerRef.current;
    if (!img || !c) return;
    const s = t.current.scale;
    const maxTx = Math.max(0, (img.offsetWidth * s - c.clientWidth) / 2);
    const maxTy = Math.max(0, (img.offsetHeight * s - c.clientHeight) / 2);
    t.current.tx = Math.min(maxTx, Math.max(-maxTx, t.current.tx));
    t.current.ty = Math.min(maxTy, Math.max(-maxTy, t.current.ty));
  };

  // Point in container coords relative to its center
  const rel = (clientX: number, clientY: number) => {
    const r = containerRef.current!.getBoundingClientRect();
    return { x: clientX - r.left - r.width / 2, y: clientY - r.top - r.height / 2 };
  };

  const onTouchStart = (e: React.TouchEvent) => {
    if (e.touches.length === 2) {
      const a = e.touches[0]!;
      const b = e.touches[1]!;
      const m = rel((a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2);
      pinch.current = {
        dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY),
        mx: m.x,
        my: m.y,
      };
      pan.current = null;
      swipe.current = null;
    } else if (e.touches.length === 1) {
      const touch = e.touches[0]!;
      if (t.current.scale > 1) {
        pan.current = {
          x: touch.clientX,
          y: touch.clientY,
          startX: touch.clientX,
          startY: touch.clientY,
        };
      } else {
        swipe.current = { x: touch.clientX, y: touch.clientY };
      }
    }
  };

  const onTouchMove = (e: React.TouchEvent) => {
    if (e.touches.length === 2 && pinch.current) {
      const a = e.touches[0]!;
      const b = e.touches[1]!;
      const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      const m = rel((a.clientX + b.clientX) / 2, (a.clientY + b.clientY) / 2);
      const s0 = t.current.scale;
      const s1 = Math.min(MAX_SCALE, Math.max(1, (s0 * dist) / pinch.current.dist));
      // Keep the content under the pinch midpoint pinned to it
      t.current.tx = m.x - ((pinch.current.mx - t.current.tx) * s1) / s0;
      t.current.ty = m.y - ((pinch.current.my - t.current.ty) * s1) / s0;
      t.current.scale = s1;
      pinch.current = { dist, mx: m.x, my: m.y };
      clampPan();
      apply(false);
    } else if (e.touches.length === 1 && pan.current) {
      const touch = e.touches[0]!;
      t.current.tx += touch.clientX - pan.current.x;
      t.current.ty += touch.clientY - pan.current.y;
      pan.current = { ...pan.current, x: touch.clientX, y: touch.clientY };
      clampPan();
      apply(false);
    }
  };

  // Double-tap toggles zoom at the tapped point
  const handleTap = (clientX: number, clientY: number) => {
    const now = Date.now();
    const prev = lastTap.current;
    const isDoubleTap =
      now - prev.time < 300 && Math.hypot(clientX - prev.x, clientY - prev.y) < 40;
    lastTap.current = { time: isDoubleTap ? 0 : now, x: clientX, y: clientY };
    if (!isDoubleTap) return;
    if (t.current.scale > 1) {
      reset(true);
    } else {
      const m = rel(clientX, clientY);
      t.current = {
        scale: DOUBLE_TAP_SCALE,
        tx: m.x * (1 - DOUBLE_TAP_SCALE),
        ty: m.y * (1 - DOUBLE_TAP_SCALE),
      };
      clampPan();
      apply(true);
    }
  };

  const onTouchEnd = (e: React.TouchEvent) => {
    if (e.touches.length === 1 && pinch.current) {
      // One finger lifted mid-pinch: continue as a pan
      pinch.current = null;
      const touch = e.touches[0]!;
      pan.current =
        t.current.scale > 1
          ? { x: touch.clientX, y: touch.clientY, startX: touch.clientX, startY: touch.clientY }
          : null;
      return;
    }
    if (e.touches.length > 0) return;

    if (pinch.current) {
      pinch.current = null;
      if (t.current.scale < 1.05) reset(true);
      return;
    }
    if (pan.current) {
      const { startX, startY } = pan.current;
      pan.current = null;
      const touch = e.changedTouches[0]!;
      if (Math.hypot(touch.clientX - startX, touch.clientY - startY) < 10) {
        handleTap(touch.clientX, touch.clientY);
      }
      return;
    }
    if (!swipe.current) return;

    const touch = e.changedTouches[0]!;
    const dx = touch.clientX - swipe.current.x;
    const dy = touch.clientY - swipe.current.y;
    swipe.current = null;

    if (Math.abs(dx) < 10 && Math.abs(dy) < 10) {
      handleTap(touch.clientX, touch.clientY);
    } else if (Math.abs(dx) > 50 && Math.abs(dy) < 80) {
      if (dx < 0) onSwipeLeft();
      else onSwipeRight();
    }
  };

  return { imgRef, containerRef, onTouchStart, onTouchMove, onTouchEnd };
}

function getTagColor(name: string): { bg: string; bgHover: string; text: string } {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = ((hash << 5) - hash + name.charCodeAt(i)) | 0;
  }
  const hue = ((hash % 360) + 360) % 360;
  return {
    bg: `hsl(${hue}, 55%, 93%)`,
    bgHover: `hsl(${hue}, 55%, 87%)`,
    text: `hsl(${hue}, 60%, 32%)`,
  };
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}
