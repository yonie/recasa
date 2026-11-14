import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, EyeOff, Pencil, X } from "lucide-react";
import { api, collageUrl, type PersonSummary } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import { CollageButton } from "../../components/CollagePopover";
import { BackButton, ErrorState, PageHeader, PageSpinner, PhotoListLayout } from "../../components/Page";
import { plural } from "../../lib/format";
import { ignoreConfirmText, personName } from "./names";

// Person detail view (route: /people/:personId)
export function PersonDetail() {
  const { personId } = useParams<{ personId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const id = Number(personId);

  const personQuery = useQuery({
    queryKey: queryKeys.person(id),
    queryFn: () => api.getPerson(id),
    enabled: !!personId,
  });
  const photosQuery = useQuery({
    queryKey: queryKeys.personPhotos(id),
    queryFn: () => api.getPersonPhotos(id, { page_size: 200 }),
    enabled: !!personId,
  });
  const person = personQuery.data;
  const photos = photosQuery.data?.items ?? [];

  const handleIgnore = async () => {
    if (!person || !window.confirm(ignoreConfirmText(person, "on the People page"))) return;
    try {
      await api.ignorePerson(person.person_id);
    } catch {
      return;
    }
    // The people list is cached; without this the ignored person would still
    // be on it when we land there.
    void queryClient.invalidateQueries({ queryKey: queryKeys.persons });
    navigate("/people");
  };

  if (personQuery.isLoading || photosQuery.isLoading) return <PageSpinner />;
  if (!person) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <p>Person not found</p>
      </div>
    );
  }
  if (photosQuery.error) return <ErrorState error={photosQuery.error} />;

  return (
    <PhotoListLayout
      photos={photos}
      header={
        <PageHeader className="flex items-center gap-3">
          <BackButton onClick={() => navigate("/people")} />

          {person.face_thumbnail_url && (
            <img src={person.face_thumbnail_url} alt="" className="w-10 h-10 rounded-full object-cover" />
          )}

          <PersonName person={person} />

          <div className="ml-auto flex items-center gap-1">
            <CollageButton
              url={collageUrl.person(person.person_id)}
              label={`${personName(person)} — Collage`}
              photoCount={photos.length}
            />
            <button
              onClick={handleIgnore}
              className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors text-gray-400 hover:text-gray-600"
              title="Ignore this person"
            >
              <EyeOff className="w-4 h-4" />
            </button>
          </div>
        </PageHeader>
      }
    />
  );
}

/** The name with its pencil; turns into an input to rename. */
function PersonName({ person }: { person: PersonSummary }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [input, setInput] = useState("");

  const startEdit = () => {
    setInput(person.name || "");
    setEditing(true);
  };

  const save = async () => {
    const name = input.trim();
    if (!name) return;
    try {
      const updated = await api.updatePerson(person.person_id, name);
      queryClient.setQueryData(queryKeys.person(person.person_id), updated);
      // The new name must show up everywhere it's cached: the people list,
      // group listings and the sidebar's named-people count.
      for (const queryKey of [
        queryKeys.persons,
        queryKeys.personGroups,
        queryKeys.hiddenGroups,
        queryKeys.togetherPersonsAll,
        queryKeys.stats,
      ]) {
        void queryClient.invalidateQueries({ queryKey });
      }
      setEditing(false);
    } catch {
      // Keep the input open so the name isn't lost.
    }
  };

  if (editing) {
    return (
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void save();
            if (e.key === "Escape") setEditing(false);
          }}
          className="px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:border-primary-400"
          autoFocus
        />
        <button onClick={save} className="p-1 hover:bg-gray-100 rounded">
          <Check className="w-4 h-4 text-green-600" />
        </button>
        <button onClick={() => setEditing(false)} className="p-1 hover:bg-gray-100 rounded">
          <X className="w-4 h-4 text-gray-400" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <h1 className="text-lg font-semibold">{personName(person)}</h1>
      <button onClick={startEdit} className="p-1 hover:bg-gray-100 rounded">
        <Pencil className="w-4 h-4 text-gray-400" />
      </button>
      <span className="text-sm text-gray-400">
        {person.photo_count} {plural(person.photo_count, "photo")}
      </span>
    </div>
  );
}
