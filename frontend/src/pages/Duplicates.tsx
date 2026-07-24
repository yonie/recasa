import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type DuplicatePhotoSummary } from "../api/client";
import { useStore } from "../store/useStore";
import { thumbnailUrl } from "../api/client";
import { Loader2, Copy, MapPin, Camera, Users, Calendar, Flag } from "lucide-react";

export function Duplicates() {
  const openViewer = useStore((s) => s.openViewer);
  const setStats = useStore((s) => s.setStats);
  const queryClient = useQueryClient();

  const { data, isLoading: loading } = useQuery({
    queryKey: ["duplicates"],
    queryFn: () => api.getDuplicates({ page_size: 50 }),
  });
  const groups = data ?? [];

  const handleFlag = useCallback(
    async (photo: DuplicatePhotoSummary) => {
      try {
        await api.toggleFlag(photo.file_hash);
        api.getStats().then(setStats).catch(() => {});
        // Flagged photo leaves duplicate groups; refetch updates the page.
        queryClient.invalidateQueries();
      } catch {
        // ignore
      }
    },
    [queryClient, setStats]
  );

  const handlePhotoClick = useCallback(
    async (photo: DuplicatePhotoSummary, groupPhotos: DuplicatePhotoSummary[]) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
        const index = groupPhotos.findIndex((p) => p.file_hash === photo.file_hash);
        openViewer(detail, groupPhotos, index);
      } catch {
        // ignore
      }
    },
    [openViewer]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
        <Copy className="w-12 h-12 text-gray-300" />
        <p className="text-lg">No duplicates found</p>
        <p className="text-sm">Duplicate detection runs during initial scan</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100">
        <h1 className="text-lg font-semibold">
          Duplicate Photos
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {groups.length} group{groups.length !== 1 ? "s" : ""}
          </span>
        </h1>
      </div>

      <div className="p-4 space-y-6">
        {groups.map((group) => (
          <div
            key={group.group_id}
            className="border border-gray-200 rounded-xl p-4"
          >
            <h3 className="text-sm font-medium text-gray-500 mb-3">
              Group {group.group_id} - {group.photos.length} photos
            </h3>
            <div className="flex gap-3 overflow-x-auto">
              {group.photos.map((photo) => (
                <div
                  key={photo.file_hash}
                  className="flex-shrink-0 w-56 cursor-pointer group relative"
                  onClick={() => handlePhotoClick(photo, group.photos)}
                >
                  <div className="aspect-square rounded-lg overflow-hidden bg-gray-100 relative">
                    <img
                      src={thumbnailUrl(photo.file_hash, 600)}
                      alt={photo.file_name}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform"
                    />
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleFlag(photo);
                      }}
                      className="absolute top-2 right-2 p-1.5 rounded-full bg-black/40 text-white
                                 opacity-0 group-hover:opacity-100 hover:bg-red-500/80 transition-all"
                      title="Flag this copy for removal"
                    >
                      <Flag className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="mt-1.5 text-xs space-y-0.5">
                    <p className="text-gray-600 truncate" title={photo.file_path}>{photo.file_path}</p>
                    <div className="flex items-center gap-3 text-gray-400">
                      {photo.width && photo.height && (
                        <span>{photo.width}x{photo.height}</span>
                      )}
                      <span>{formatBytes(photo.file_size)}</span>
                    </div>
                    {photo.date_taken && (
                      <p className="text-gray-400 flex items-center gap-1">
                        <Calendar className="w-3 h-3" />
                        {new Date(photo.date_taken).toLocaleString(undefined, {
                          year: "numeric", month: "short", day: "numeric",
                          hour: "2-digit", minute: "2-digit", second: "2-digit",
                        })}
                      </p>
                    )}
                    {photo.location && (
                      <p className="text-gray-400 flex items-center gap-1 truncate">
                        <MapPin className="w-3 h-3 flex-shrink-0" />
                        {photo.location}
                      </p>
                    )}
                    {photo.camera && (
                      <p className="text-gray-400 flex items-center gap-1 truncate">
                        <Camera className="w-3 h-3 flex-shrink-0" />
                        {photo.camera}
                      </p>
                    )}
                    {photo.people.length > 0 && (
                      <p className="text-gray-400 flex items-center gap-1 truncate">
                        <Users className="w-3 h-3 flex-shrink-0" />
                        {photo.people.join(", ")}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
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
