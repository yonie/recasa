import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import { api, collageUrl, thumbnailUrl, type YearCount } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { CollageButton } from "../components/CollagePopover";
import { GridViewControls } from "../components/GridViewControls";
import { ErrorState, PageSpinner } from "../components/Page";
import { TimelineGroups } from "../components/TimelineGroups";
import { formatMonthName, plural } from "../lib/format";

export function Years() {
  const { year: yearParam } = useParams<{ year: string }>();
  const selectedYear = yearParam ? Number(yearParam) : null;

  const { data: years = [], isLoading, error } = useQuery({
    queryKey: queryKeys.years,
    queryFn: api.getYears,
  });

  if (isLoading) return <PageSpinner />;
  if (error) return <ErrorState error={error} />;
  if (!selectedYear) return <YearPicker years={years} />;
  return (
    <YearDetail
      year={selectedYear}
      photoCount={years.find((y) => y.year === selectedYear)?.count ?? 0}
    />
  );
}

function YearPicker({ years }: { years: YearCount[] }) {
  const navigate = useNavigate();
  return (
    <div className="p-6 overflow-y-auto h-full">
      <h1 className="text-xl font-semibold text-gray-800 mb-6">Browse by Year</h1>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
        {years.map(({ year, count, previews }) => (
          <button
            key={year}
            onClick={() => navigate(`/years/${year}`)}
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
                {count.toLocaleString()} {plural(count, "photo")}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function YearDetail({ year, photoCount }: { year: number; photoCount: number }) {
  const navigate = useNavigate();
  const { data: groups = [], isLoading, error } = useQuery({
    queryKey: queryKeys.timeline("year", year),
    queryFn: () => api.getTimeline({ year, group_by: "month", limit: 12 }),
  });

  return (
    <div className="overflow-y-auto h-full">
      <div className="sticky top-0 bg-white z-10 px-4 py-3 border-b border-gray-200 flex items-center gap-3">
        <button onClick={() => navigate("/years")} className="p-1 hover:bg-gray-100 rounded">
          <ChevronLeft className="w-5 h-5" />
        </button>
        <h1 className="text-lg font-semibold">{year}</h1>
        <div className="ml-auto">
          <CollageButton url={collageUrl.year(year)} label={`${year}: Collage`} photoCount={photoCount} />
        </div>
      </div>

      {isLoading ? (
        <PageSpinner />
      ) : error ? (
        <ErrorState error={error} />
      ) : (
        <TimelineGroups
          groups={groups}
          label={formatMonthName}
          count={(g) => `${g.count} ${plural(g.count, "photo")}`}
          headingClassName="top-12 z-[5]"
        />
      )}
      <GridViewControls />
    </div>
  );
}
