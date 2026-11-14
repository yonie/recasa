import { useQuery } from "@tanstack/react-query";
import { Flag, X } from "lucide-react";
import { api, thumbnailUrl, type PhotoSummary } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { EmptyState, ErrorState, PageHeader, PageSpinner, PageTitle } from "../components/Page";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { usePhotoActions } from "../hooks/usePhotoActions";
import { formatBytes, plural } from "../lib/format";

/**
 * Photos flagged for removal. The app never deletes files: this page lists
 * each flagged photo with its path so the user can remove it on disk
 * themselves; the periodic sweep then cleans the index.
 */
export function Flagged() {
  const openPhoto = useOpenPhoto();
  const { toggleFlag } = usePhotoActions();

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.photoList({ flagged: true }),
    queryFn: () => api.getPhotos({ flagged: true, page_size: 200, sort: "file_name", order: "asc" }),
  });
  const photos = data?.items ?? [];

  const handleUnflag = (photo: PhotoSummary) => toggleFlag(photo.file_hash).catch(() => {});

  if (isLoading) return <PageSpinner />;
  if (error) return <ErrorState error={error} />;
  if (photos.length === 0) {
    return (
      <EmptyState
        icon={Flag}
        title="Nothing flagged for removal"
        hint="Flag photos with the flag icon, or press R in the viewer. Flagged photos are hidden from all other views."
      />
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <PageHeader>
        <PageTitle count={`${photos.length} ${plural(photos.length, "photo")}`}>
          Flagged for removal
        </PageTitle>
        <p className="text-xs text-gray-500 mt-0.5">
          Recasa never deletes files. Remove these from disk yourself — the index cleans up
          automatically on the next sweep.
        </p>
      </PageHeader>

      <div className="divide-y divide-gray-50">
        {photos.map((photo, index) => (
          <div key={photo.file_hash} className="flex items-center gap-3 px-4 py-2 hover:bg-gray-50">
            <img
              src={thumbnailUrl(photo.file_hash, 200)}
              alt={photo.file_name}
              loading="lazy"
              className="w-16 h-16 rounded object-cover cursor-pointer shrink-0"
              onClick={() => openPhoto(photo, index, photos)}
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
