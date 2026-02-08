import { useEffect, useState, useCallback } from "react";
import { api, type DuplicateGroup, type PhotoSummary } from "../api/client";
import { useStore } from "../store/useStore";
import { thumbnailUrl } from "../api/client";
import { Loader2, Copy } from "lucide-react";

export function Duplicates() {
  const [groups, setGroups] = useState<DuplicateGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      try {
        const data = await api.getDuplicates({ page_size: 50 });
        setGroups(data);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary, groupPhotos: PhotoSummary[]) => {
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
                  className="flex-shrink-0 w-40 cursor-pointer group"
                  onClick={() => handlePhotoClick(photo, group.photos)}
                >
                  <div className="aspect-square rounded-lg overflow-hidden bg-gray-100">
                    <img
                      src={thumbnailUrl(photo.file_hash, 200)}
                      alt={photo.file_name}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform"
                    />
                  </div>
                  <p className="text-xs text-gray-500 mt-1 truncate">{photo.file_name}</p>
                  <p className="text-xs text-gray-400">{formatBytes(photo.file_size)}</p>
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
