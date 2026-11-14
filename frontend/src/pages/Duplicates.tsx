import { useQuery } from "@tanstack/react-query";
import { Calendar, Camera, Copy, Flag, MapPin, Users } from "lucide-react";
import { api, thumbnailUrl, type DuplicatePhotoSummary } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { EmptyState, ErrorState, PageHeader, PageSpinner, PageTitle } from "../components/Page";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { usePhotoActions } from "../hooks/usePhotoActions";
import { formatBytes, plural } from "../lib/format";

export function Duplicates() {
  const openPhoto = useOpenPhoto();
  // A flagged copy leaves its duplicate group; the refetch updates the page.
  const { toggleFlag } = usePhotoActions();

  const { data: groups = [], isLoading, error } = useQuery({
    queryKey: queryKeys.duplicates,
    queryFn: () => api.getDuplicates({ page_size: 50 }),
  });

  if (isLoading) return <PageSpinner />;
  if (error) return <ErrorState error={error} />;
  if (groups.length === 0) {
    return (
      <EmptyState
        icon={Copy}
        title="No duplicates found"
        hint="Duplicate detection runs during initial scan"
      />
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <PageHeader>
        <PageTitle count={`${groups.length} ${plural(groups.length, "group")}`}>Duplicate Photos</PageTitle>
      </PageHeader>

      <div className="p-4 space-y-6">
        {groups.map((group) => (
          <div key={group.group_id} className="border border-gray-200 rounded-xl p-4">
            <h3 className="text-sm font-medium text-gray-500 mb-3">
              Group {group.group_id} - {group.photos.length} photos
            </h3>
            <div className="flex gap-3 overflow-x-auto">
              {group.photos.map((photo, index) => (
                <DuplicateCard
                  key={photo.file_hash}
                  photo={photo}
                  onOpen={() => openPhoto(photo, index, group.photos)}
                  onFlag={() => toggleFlag(photo.file_hash).catch(() => {})}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DuplicateCard({
  photo,
  onOpen,
  onFlag,
}: {
  photo: DuplicatePhotoSummary;
  onOpen: () => void;
  onFlag: () => void;
}) {
  return (
    <div className="flex-shrink-0 w-56 cursor-pointer group relative" onClick={onOpen}>
      <div className="aspect-square rounded-lg overflow-hidden bg-gray-100 relative">
        <img
          src={thumbnailUrl(photo.file_hash, 600)}
          alt={photo.file_name}
          loading="lazy"
          decoding="async"
          className="w-full h-full object-cover group-hover:scale-105 transition-transform"
        />
        <button
          onClick={(e) => {
            e.stopPropagation();
            onFlag();
          }}
          className="absolute top-2 right-2 p-1.5 rounded-full bg-black/40 text-white
                     opacity-0 group-hover:opacity-100 hover:bg-red-500/80 transition-all"
          title="Flag this copy for removal"
        >
          <Flag className="w-4 h-4" />
        </button>
      </div>
      <div className="mt-1.5 text-xs space-y-0.5">
        <p className="text-gray-600 truncate" title={photo.file_path}>
          {photo.file_path}
        </p>
        <div className="flex items-center gap-3 text-gray-400">
          {photo.width && photo.height && (
            <span>
              {photo.width}x{photo.height}
            </span>
          )}
          <span>{formatBytes(photo.file_size)}</span>
        </div>
        {photo.date_taken && (
          <p className="text-gray-400 flex items-center gap-1">
            <Calendar className="w-3 h-3" />
            {new Date(photo.date_taken).toLocaleString(undefined, {
              year: "numeric",
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
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
  );
}
