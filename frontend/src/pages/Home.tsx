import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type PhotoSummary } from "../api/client";
import { PhotoGrid, GridViewControls } from "../components/PhotoGrid";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { Loader2 } from "lucide-react";

export function Home() {
  const openPhoto = useOpenPhoto();

  const { data, isLoading, error } = useQuery({
    queryKey: ["timeline", "month", 24, "photos-only"],
    queryFn: () => api.getTimeline({ group_by: "month", limit: 24, video: false }),
  });
  const groups = data ?? [];

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

  if (error) {
    return (
      <div className="flex items-center justify-center h-64 text-red-500">
        <p>{error instanceof Error ? error.message : "Failed to load photos"}</p>
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
          <div className="sticky top-0 bg-white/95 z-10 px-4 py-2 border-b border-gray-100">
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
            showControls={false}
          />
        </div>
      ))}
      <GridViewControls />
    </div>
  );
}

function formatGroupDate(dateStr: string): string {
  if (dateStr === "unknown") {
    return "Unknown Date";
  }
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
