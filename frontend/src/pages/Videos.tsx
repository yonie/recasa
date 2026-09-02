import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type PhotoSummary } from "../api/client";
import { PhotoGrid, GridViewControls } from "../components/PhotoGrid";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { Loader2, Clapperboard } from "lucide-react";

export function Videos() {
  const openPhoto = useOpenPhoto();

  // Grouped by month like the Photos timeline.
  const { data, isLoading } = useQuery({
    queryKey: ["timeline", "video", "month"],
    queryFn: () => api.getTimeline({ video: true, group_by: "month", limit: 200 }),
  });
  const groups = data ?? [];
  const total = groups.reduce((n, g) => n + g.photos.length, 0);

  const handlePhotoClick = useCallback(
    (photo: PhotoSummary, index: number, groupPhotos: PhotoSummary[]) =>
      openPhoto(photo, index, groupPhotos),
    [openPhoto]
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
        <Clapperboard className="w-12 h-12 text-gray-300" />
        <p className="text-lg">No videos yet</p>
        <p className="text-sm">Videos in your library appear here once indexed</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100 sticky top-0 bg-white/95 z-20">
        <h1 className="text-lg font-semibold">
          Videos
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {total} video{total !== 1 ? "s" : ""}
          </span>
        </h1>
      </div>

      {groups.map((group) => (
        <div key={group.date}>
          <div className="sticky top-[57px] bg-white/95 z-10 px-4 py-2 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-700">
              {formatMonth(group.date)}
              <span className="ml-2 text-gray-400 font-normal">
                {group.photos.length} video{group.photos.length !== 1 ? "s" : ""}
              </span>
            </h2>
          </div>
          <PhotoGrid
            photos={group.photos}
            onPhotoClick={(photo, index) => handlePhotoClick(photo, index, group.photos)}
            showControls={false}
          />
        </div>
      ))}
      <GridViewControls />
    </div>
  );
}

function formatMonth(dateStr: string): string {
  const parts = dateStr.split("-");
  if (parts.length >= 2) {
    const date = new Date(parseInt(parts[0]!), parseInt(parts[1]!) - 1);
    return date.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  }
  return dateStr;
}
