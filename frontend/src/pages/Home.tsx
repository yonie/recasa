import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { GridViewControls } from "../components/GridViewControls";
import { EmptyState, ErrorState, PageSpinner } from "../components/Page";
import { TimelineGroups } from "../components/TimelineGroups";
import { formatGroupDate, plural } from "../lib/format";

export function Home() {
  const { data: groups, isLoading, error } = useQuery({
    queryKey: queryKeys.timeline("month", 24, "photos-only"),
    queryFn: () => api.getTimeline({ group_by: "month", limit: 24, video: false }),
  });

  if (isLoading) return <PageSpinner />;
  if (error) return <ErrorState error={error} />;
  if (!groups?.length) {
    return (
      <EmptyState title="No photos yet" hint="Photos will appear here once scanning completes" />
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <TimelineGroups
        groups={groups}
        label={formatGroupDate}
        count={(g) => `${g.count} ${plural(g.count, "photo")}`}
        headingClassName="top-0 z-10"
      />
      <GridViewControls />
    </div>
  );
}
