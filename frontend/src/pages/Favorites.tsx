import { useQuery } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { api, collageUrl } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { CollageButton } from "../components/CollagePopover";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  PageSpinner,
  PageTitle,
  PhotoListLayout,
} from "../components/Page";
import { plural } from "../lib/format";

export function Favorites() {
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.photoList({ favorite: true }),
    queryFn: () => api.getPhotos({ favorite: true, page_size: 200 }),
  });
  const photos = data?.items ?? [];

  if (isLoading) return <PageSpinner />;
  if (error) return <ErrorState error={error} />;
  if (photos.length === 0) {
    return (
      <EmptyState
        icon={Star}
        title="No favorites yet"
        hint="Hover over photos and click the star icon, or press F while viewing"
      />
    );
  }

  return (
    <PhotoListLayout
      photos={photos}
      header={
        <PageHeader>
          <PageTitle count={`${photos.length} ${plural(photos.length, "photo")}`}>Favorites</PageTitle>
          <div className="ml-auto">
            <CollageButton
              url={collageUrl.favorites()}
              label="Favorites — Collage"
              photoCount={photos.length}
            />
          </div>
        </PageHeader>
      }
    />
  );
}
