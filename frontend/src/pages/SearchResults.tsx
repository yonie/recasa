import { useSearchParams } from "react-router-dom";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  PageSpinner,
  PageTitle,
  PhotoListLayout,
} from "../components/Page";
import { plural } from "../lib/format";

export function SearchResults() {
  const [searchParams] = useSearchParams();
  const query = searchParams.get("q") || "";

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.search(query),
    queryFn: () => api.getPhotos({ search: query, page_size: 200 }),
    enabled: !!query,
    placeholderData: keepPreviousData,
  });

  if (isLoading) return <PageSpinner />;
  if (!query) return <EmptyState icon={Search} title="Enter a search query" />;
  if (error) return <ErrorState error={error} />;

  const total = data?.total ?? 0;
  return (
    <PhotoListLayout
      photos={data?.items ?? []}
      header={
        <PageHeader>
          <PageTitle count={`${total} ${plural(total, "result")}`}>Search: "{query}"</PageTitle>
        </PageHeader>
      }
    />
  );
}
