import { useEffect, useCallback, useState, useRef } from "react";
import {
  X,
  Star,
  MapPin,
  Camera,
  Clock,
  HardDrive,
  Info,
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  Users,
} from "lucide-react";
import { clsx } from "clsx";
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
  
  // Track if we pushed a history state for this viewer
  const historyPushed = useRef(false);
  const [detail, setDetail] = useState<PhotoDetail | null>(null);
  const [showInfo, setShowInfo] = useState(false);
  const [isFavorite, setIsFavorite] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (viewerPhoto) {
      setDetail(viewerPhoto);
      setIsFavorite(viewerPhoto.is_favorite);
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
      if (e.key === "Escape") closeViewer();
      if (e.key === "i") setShowInfo((s) => !s);
      if (e.key === "ArrowLeft" && canGoPrev) navigateTo(viewerIndex - 1);
      if (e.key === "ArrowRight" && canGoNext) navigateTo(viewerIndex + 1);
      if (e.key === "f" || e.key === "s") {
        // Star/favorite toggle
        if (detail) handleFavorite();
      }
    },
    [closeViewer, canGoPrev, canGoNext, viewerIndex, navigateTo, detail]
  );

  // Handle browser back button to close viewer
  useEffect(() => {
    if (viewerOpen) {
      // Push a history state when opening viewer
      if (!historyPushed.current) {
        window.history.pushState({ viewerOpen: true }, "");
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
      // Reset history flag when viewer closes
      historyPushed.current = false;
    }
  }, [viewerOpen, handleKeyDown, closeViewer]);

  const handleFavorite = useCallback(async () => {
    if (!detail) return;
    try {
      const result = await api.toggleFavorite(detail.file_hash);
      setIsFavorite(result.is_favorite);
    } catch {
      // ignore
    }
  }, [detail]);

  if (!viewerOpen || !detail) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/95 flex">
      {/* Main image */}
      <div
        className="flex-1 flex items-center justify-center relative"
        onClick={closeViewer}
      >
        <img
          src={originalUrl(detail.file_hash)}
          alt={detail.file_name}
          className={clsx(
            "max-w-full max-h-full object-contain transition-opacity duration-200",
            loading && "opacity-50"
          )}
          onClick={(e) => e.stopPropagation()}
        />

        {/* Top toolbar */}
        <div className="absolute top-0 left-0 right-0 flex items-center justify-between p-4">
          <button
            onClick={closeViewer}
            className="p-2 rounded-full bg-black/40 hover:bg-black/60 text-white transition-colors"
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
              className="p-2 rounded-full bg-black/40 hover:bg-black/60 text-white transition-colors"
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
                setShowInfo((s) => !s);
              }}
              className={clsx(
                "p-2 rounded-full transition-colors",
                showInfo
                  ? "bg-white/20 text-white"
                  : "bg-black/40 hover:bg-black/60 text-white"
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
            className="absolute left-4 top-1/2 -translate-y-1/2 p-2 rounded-full bg-black/40 hover:bg-black/60 text-white transition-colors"
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
            className="absolute right-4 top-1/2 -translate-y-1/2 p-2 rounded-full bg-black/40 hover:bg-black/60 text-white transition-colors"
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
        <div className="w-80 bg-gray-900 text-white overflow-y-auto border-l border-gray-700">
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

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}
