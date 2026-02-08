import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type PhotoSummary } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { Loader2, Search } from "lucide-react";

export function SearchResults() {
  const [searchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      if (!query) {
        setPhotos([]);
        setTotal(0);
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        const data = await api.getPhotos({ search: query, page_size: 200 });
        setPhotos(data.items);
        setTotal(data.total);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [query]);

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

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  if (!query) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
        <Search className="w-12 h-12 text-gray-300" />
        <p className="text-lg">Enter a search query</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100">
        <h1 className="text-lg font-semibold">
          Search: "{query}"
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {total} result{total !== 1 ? "s" : ""}
          </span>
        </h1>
      </div>
      <PhotoGrid photos={photos} onPhotoClick={handlePhotoClick} />
    </div>
  );
}
