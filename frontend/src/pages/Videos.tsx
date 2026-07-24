import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type PhotoSummary } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { Loader2, Clapperboard } from "lucide-react";

export function Videos() {
  const openViewer = useStore((s) => s.openViewer);

  const { data, isLoading } = useQuery({
    queryKey: ["photos", { video: true }],
    queryFn: () => api.getPhotos({ video: true, page_size: 200 }),
  });
  const videos = data?.items ?? [];

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary, index: number) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
        openViewer(detail, videos, index);
      } catch {
        // ignore
      }
    },
    [openViewer, videos]
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  if (videos.length === 0) {
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
      <div className="px-4 py-3 border-b border-gray-100">
        <h1 className="text-lg font-semibold">
          Videos
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {videos.length} video{videos.length !== 1 ? "s" : ""}
          </span>
        </h1>
      </div>
      <PhotoGrid photos={videos} onPhotoClick={handlePhotoClick} />
    </div>
  );
}
