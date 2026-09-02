import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, thumbnailUrl, type PhotoSummary } from "../api/client";
import { useStore } from "../store/useStore";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { Loader2, Flag, X } from "lucide-react";

/**
 * Photos flagged for removal. The app never deletes files — this page lists
 * each flagged photo with its path so the user can remove it on disk
 * themselves; the periodic sweep then cleans the index.
 */
export function Flagged() {
  const openPhoto = useOpenPhoto();
  const setStats = useStore((s) => s.setStats);
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["photos", { flagged: true }],
    queryFn: () => api.getPhotos({ flagged: true, page_size: 200, sort: "file_name", order: "asc" }),
  });
  const photos = data?.items ?? [];

  const handleUnflag = useCallback(
    async (photo: PhotoSummary) => {
      try {
        await api.toggleFlag(photo.file_hash);
        api.getStats().then(setStats).catch(() => {});
        queryClient.invalidateQueries();
      } catch {
        // ignore
      }
    },
    [queryClient, setStats]
  );

  const handleOpen = useCallback(
    (photo: PhotoSummary, index: number) => openPhoto(photo, index, photos),
    [openPhoto, photos]
  );

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
        <Flag className="w-12 h-12 text-gray-300" />
        <p className="text-lg">Nothing flagged for removal</p>
        <p className="text-sm">
          Flag photos with the flag icon, or press R in the viewer. Flagged photos are hidden
          from all other views.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100">
        <h1 className="text-lg font-semibold">
          Flagged for removal
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {photos.length} photo{photos.length !== 1 ? "s" : ""}
          </span>
        </h1>
        <p className="text-xs text-gray-500 mt-0.5">
          Recasa never deletes files. Remove these from disk yourself — the index cleans up
          automatically on the next sweep.
        </p>
      </div>

      <div className="divide-y divide-gray-50">
        {photos.map((photo, index) => (
          <div key={photo.file_hash} className="flex items-center gap-3 px-4 py-2 hover:bg-gray-50">
            <img
              src={thumbnailUrl(photo.file_hash, 200)}
              alt={photo.file_name}
              loading="lazy"
              className="w-16 h-16 rounded object-cover cursor-pointer shrink-0"
              onClick={() => handleOpen(photo, index)}
            />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-mono text-gray-700 break-all">{photo.file_path}</p>
              <p className="text-xs text-gray-400">
                {formatBytes(photo.file_size)}
                {photo.width && photo.height ? ` · ${photo.width} × ${photo.height}` : ""}
              </p>
            </div>
            <button
              onClick={() => handleUnflag(photo)}
              className="shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-lg border border-gray-200
                         text-gray-600 hover:bg-gray-100 transition-colors"
              title="Remove flag — photo returns to normal views"
            >
              <X className="w-3.5 h-3.5" />
              Unflag
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}
