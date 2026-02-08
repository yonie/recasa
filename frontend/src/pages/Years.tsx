import { useEffect, useState, useCallback } from "react";
import { api, type YearCount, type PhotoSummary, type TimelineGroup } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { Loader2, ChevronLeft } from "lucide-react";

export function Years() {
  const [years, setYears] = useState<YearCount[]>([]);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [groups, setGroups] = useState<TimelineGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [photosLoading, setPhotosLoading] = useState(false);
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      try {
        const data = await api.getYears();
        setYears(data);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const handleSelectYear = useCallback(async (year: number) => {
    setSelectedYear(year);
    setPhotosLoading(true);
    try {
      const data = await api.getTimeline({ year, group_by: "month", limit: 12 });
      setGroups(data);
    } catch {
      setGroups([]);
    } finally {
      setPhotosLoading(false);
    }
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

  // Year selection view
  if (!selectedYear) {
    return (
      <div className="p-6">
        <h1 className="text-xl font-semibold text-gray-800 mb-6">Browse by Year</h1>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {years.map(({ year, count }) => (
            <button
              key={year}
              onClick={() => handleSelectYear(year)}
              className="p-6 bg-gray-50 rounded-xl hover:bg-primary-50 hover:text-primary-700
                         border border-gray-200 hover:border-primary-200
                         transition-all text-center group"
            >
              <div className="text-2xl font-bold group-hover:text-primary-700">{year}</div>
              <div className="text-sm text-gray-500 mt-1">
                {count.toLocaleString()} photo{count !== 1 ? "s" : ""}
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
          onClick={() => setSelectedYear(null)}
          className="p-1 hover:bg-gray-100 rounded"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>
        <h1 className="text-lg font-semibold">{selectedYear}</h1>
      </div>

      {photosLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
        </div>
      ) : (
        groups.map((group) => (
          <div key={group.date}>
            <div className="sticky top-12 bg-white/90 backdrop-blur-sm z-[5] px-4 py-2 border-b border-gray-100">
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
