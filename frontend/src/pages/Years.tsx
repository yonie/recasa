import { useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, thumbnailUrl, type PhotoSummary } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { Loader2, ChevronLeft } from "lucide-react";
import { CollageButton } from "../components/CollagePopover";

export function Years() {
  const { year: yearParam } = useParams<{ year: string }>();
  const navigate = useNavigate();
  const selectedYear = yearParam ? Number(yearParam) : null;
  const openViewer = useStore((s) => s.openViewer);

  const { data: yearsData, isLoading: loading } = useQuery({
    queryKey: ["years"],
    queryFn: () => api.getYears(),
  });
  const years = yearsData ?? [];

  const { data: groupsData, isLoading: photosLoading } = useQuery({
    queryKey: ["timeline", "year", selectedYear],
    queryFn: () => api.getTimeline({ year: selectedYear!, group_by: "month", limit: 12 }),
    enabled: selectedYear !== null,
  });
  const groups = groupsData ?? [];

  const handleSelectYear = useCallback(
    (year: number) => {
      navigate(`/years/${year}`);
    },
    [navigate]
  );

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

  // Year selection view
  if (!selectedYear) {
    return (
      <div className="p-6 overflow-y-auto h-full">
        <h1 className="text-xl font-semibold text-gray-800 mb-6">Browse by Year</h1>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
          {years.map(({ year, count, previews }) => (
            <button
              key={year}
              onClick={() => handleSelectYear(year)}
              className="bg-gray-50 rounded-xl overflow-hidden hover:bg-primary-50
                         border border-gray-200 hover:border-primary-200
                         transition-all text-left group"
            >
              {previews.length > 0 && (
                <div className="grid grid-cols-4 gap-px bg-gray-200">
                  {previews.slice(0, 4).map((hash) => (
                    <img
                      key={hash}
                      src={thumbnailUrl(hash, 200)}
                      alt=""
                      loading="lazy"
                      decoding="async"
                      className="w-full aspect-square object-cover"
                    />
                  ))}
                </div>
              )}
              <div className="px-4 py-3 flex items-baseline justify-between">
                <span className="text-xl font-bold group-hover:text-primary-700">{year}</span>
                <span className="text-sm text-gray-500">
                  {count.toLocaleString()} photo{count !== 1 ? "s" : ""}
                </span>
              </div>
            </button>
          ))}
        </div>
      </div>
    );
  }

  // Year detail view
  return (
    <div className="overflow-y-auto h-full">
      <div className="sticky top-0 bg-white z-10 px-4 py-3 border-b border-gray-200 flex items-center gap-3">
        <button
          onClick={() => navigate("/years")}
          className="p-1 hover:bg-gray-100 rounded"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>
        <h1 className="text-lg font-semibold">{selectedYear}</h1>
        <div className="ml-auto">
          <CollageButton
            url={`/api/photos/collage?year=${selectedYear}`}
            label={`${selectedYear} — Collage`}
            photoCount={years.find((y) => y.year === selectedYear)?.count ?? 0}
          />
        </div>
      </div>

      {photosLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
        </div>
      ) : (
        groups.map((group) => (
          <div key={group.date}>
            <div className="sticky top-12 bg-white/95 z-[5] px-4 py-2 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-700">
                {formatMonth(group.date)}
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
        ))
      )}
    </div>
  );
}

function formatMonth(dateStr: string): string {
  const parts = dateStr.split("-");
  if (parts.length >= 2) {
    const date = new Date(parseInt(parts[0]!), parseInt(parts[1]!) - 1);
    return date.toLocaleDateString(undefined, { month: "long" });
  }
  return dateStr;
}
