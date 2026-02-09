import { useEffect, useState, useCallback } from "react";
import { api, type PhotoSummary } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { Loader2, Star } from "lucide-react";

export function Favorites() {
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const openViewer = useStore((s) => s.openViewer);

  const loadFavorites = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api.getPhotos({ favorite: true, page_size: 200 });
      setPhotos(data.items);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFavorites();
  }, [loadFavorites]);

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary, index: number) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
        openViewer(detail, photos, index);
      } catch {
        // ignore
      }
    },
    [openViewer, photos]
  );

  const handleFavoriteToggle = useCallback(() => {
    // Reload to reflect changes
    loadFavorites();
  }, [loadFavorites]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  if (photos.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
        <Star className="w-12 h-12 text-gray-300" />
        <p className="text-lg">No favorites yet</p>
        <p className="text-sm">Hover over photos and click the star icon, or press F while viewing</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100">
        <h1 className="text-lg font-semibold">
          Favorites
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {photos.length} photo{photos.length !== 1 ? "s" : ""}
          </span>
        </h1>
      </div>
      <PhotoGrid
        photos={photos}
        onPhotoClick={handlePhotoClick}
        onFavoriteToggle={handleFavoriteToggle}
      />
    </div>
  );
}
