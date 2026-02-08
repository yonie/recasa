import { useEffect, useState, useCallback } from "react";
import { api, type PhotoSummary, type TimelineGroup } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { Loader2 } from "lucide-react";

export function Home() {
  const [groups, setGroups] = useState<TimelineGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const data = await api.getTimeline({ group_by: "month", limit: 24 });
        setGroups(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load photos");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary, index: number, groupPhotos: PhotoSummary[]) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
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

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 text-red-500">
        <p>{error}</p>
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
        <p className="text-lg">No photos yet</p>
        <p className="text-sm">Photos will appear here once scanning completes</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      {groups.map((group) => (
        <div key={group.date}>
          <div className="sticky top-0 bg-white/90 backdrop-blur-sm z-10 px-4 py-2 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-700">
              {formatGroupDate(group.date)}
              <span className="ml-2 text-gray-400 font-normal">
                {group.count} photo{group.count !== 1 ? "s" : ""}
              </span>
            </h2>
          </div>
          <PhotoGrid
            photos={group.photos}
            onPhotoClick={(photo, index) => handlePhotoClick(photo, index, group.photos)}
          />
        </div>
      ))}
    </div>
  );
}

function formatGroupDate(dateStr: string): string {
  const parts = dateStr.split("-");
  if (parts.length === 1) {
    return parts[0]!;
  }
  if (parts.length === 2) {
    const date = new Date(parseInt(parts[0]!), parseInt(parts[1]!) - 1);
    return date.toLocaleDateString(undefined, { year: "numeric", month: "long" });
  }
  const date = new Date(dateStr);
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}
