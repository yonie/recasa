import { useQuery } from "@tanstack/react-query";
import { Clapperboard } from "lucide-react";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { GridViewControls } from "../components/GridViewControls";
import { EmptyState, ErrorState, PageHeader, PageSpinner, PageTitle } from "../components/Page";
import { TimelineGroups } from "../components/TimelineGroups";
import { formatGroupDate, plural } from "../lib/format";

export function Videos() {
  // Grouped by month like the Photos timeline.
  const { data: groups, isLoading, error } = useQuery({
    queryKey: queryKeys.timeline("video", "month"),
    queryFn: () => api.getTimeline({ video: true, group_by: "month", limit: 200 }),
  });

  if (isLoading) return <PageSpinner />;
  if (error) return <ErrorState error={error} />;
  if (!groups?.length) {
    return (
      <EmptyState
        icon={Clapperboard}
        title="No videos yet"
        hint="Videos in your library appear here once indexed"
      />
    );
  }

  const total = groups.reduce((n, g) => n + g.photos.length, 0);
  return (
    <div className="overflow-y-auto h-full">
      <PageHeader className="sticky top-0 bg-white/95 z-20">
        <PageTitle count={`${total} ${plural(total, "video")}`}>Videos</PageTitle>
      </PageHeader>
      <TimelineGroups
        groups={groups}
        label={formatGroupDate}
        count={(g) => `${g.photos.length} ${plural(g.photos.length, "video")}`}
        headingClassName="top-[57px] z-10"
      />
      <GridViewControls />
    </div>
  );
}
