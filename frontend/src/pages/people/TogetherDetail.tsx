import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, collageUrl } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import { CollageButton } from "../../components/CollagePopover";
import { BackButton, ErrorState, PageHeader, PageSpinner, PhotoListLayout } from "../../components/Page";
import { FaceStack } from "./FaceStack";
import { groupNames } from "./names";

// Together detail view (route: /people/together/:personIds)
export function TogetherDetail() {
  const { personIds } = useParams<{ personIds: string }>();
  const navigate = useNavigate();
  const ids = (personIds ?? "").split(",").map(Number).filter(Boolean);
  const enabled = ids.length >= 2;

  const personsQuery = useQuery({
    queryKey: queryKeys.togetherPersons(personIds),
    queryFn: () => Promise.all(ids.map((id) => api.getPerson(id))),
    enabled,
  });
  const photosQuery = useQuery({
    queryKey: queryKeys.togetherPhotos(personIds),
    queryFn: () => api.getSharedPhotosN(ids, { page_size: 200 }),
    enabled,
  });
  const persons = personsQuery.data ?? [];
  const photos = photosQuery.data?.items ?? [];

  if (personsQuery.isLoading || photosQuery.isLoading) return <PageSpinner />;
  if (photosQuery.error) return <ErrorState error={photosQuery.error} />;

  return (
    <PhotoListLayout
      photos={photos}
      header={
        <PageHeader className="flex items-center gap-3">
          <BackButton onClick={() => navigate("/people")} />
          <FaceStack persons={persons} />
          <div>
            <h1 className="text-lg font-semibold">{groupNames(persons)}</h1>
            <span className="text-xs text-gray-400">{photos.length} shared photos</span>
          </div>
          {persons.length >= 2 && (
            <div className="ml-auto">
              <CollageButton
                url={collageUrl.together(persons.map((p) => p.person_id))}
                label={`${groupNames(persons)} — Collage`}
                photoCount={photos.length}
              />
            </div>
          )}
        </PageHeader>
      }
    />
  );
}
