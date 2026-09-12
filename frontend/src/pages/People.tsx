import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type PersonSummary, type PhotoSummary, thumbnailUrl } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { useScrollRestore } from "../hooks/useScrollRestore";
import { Loader2, Users, ArrowLeft, Pencil, Check, X, EyeOff, Eye, ChevronDown } from "lucide-react";
import { CollageButton } from "../components/CollagePopover";

function personName(p: PersonSummary): string {
  return p.name || `Person ${p.person_id}`;
}

function groupNames(persons: PersonSummary[]): string {
  if (persons.length <= 2) return persons.map(personName).join(" & ");
  return persons.slice(0, -1).map(personName).join(", ") + " & " + personName(persons[persons.length - 1]!);
}

// Person detail view (route: /people/:personId)
export function PersonDetail() {
  const { personId } = useParams<{ personId: string }>();
  const navigate = useNavigate();
  const [editingName, setEditingName] = useState(false);
  const [nameInput, setNameInput] = useState("");
  const openPhoto = useOpenPhoto();
  const setStats = useStore((s) => s.setStats);
  const queryClient = useQueryClient();
  const id = Number(personId);

  const { data: person, isLoading: personLoading } = useQuery({
    queryKey: ["person", id],
    queryFn: () => api.getPerson(id),
    enabled: !!personId,
  });
  const { data: photosPage, isLoading: photosLoading } = useQuery({
    queryKey: ["person-photos", id],
    queryFn: () => api.getPersonPhotos(id, { page_size: 200 }),
    enabled: !!personId,
  });
  const photos = photosPage?.items ?? [];
  const loading = personLoading || photosLoading;

  const handlePhotoClick = useCallback(
    (photo: PhotoSummary, index: number) => openPhoto(photo, index, photos),
    [openPhoto, photos]
  );

  const handleStartEdit = useCallback(() => {
    if (person) {
      setNameInput(person.name || "");
      setEditingName(true);
    }
  }, [person]);

  const handleSaveName = useCallback(async () => {
    if (!person || !nameInput.trim()) return;
    try {
      const updated = await api.updatePerson(person.person_id, nameInput.trim());
      queryClient.setQueryData(["person", id], updated);
      // The new name must show up everywhere it's cached: the people list,
      // group listings and the sidebar's named-people count.
      queryClient.invalidateQueries({ queryKey: ["persons"] });
      queryClient.invalidateQueries({ queryKey: ["person-groups"] });
      queryClient.invalidateQueries({ queryKey: ["persons-together"] });
      api.getStats().then(setStats).catch(() => {});
      setEditingName(false);
    } catch {
      // ignore
    }
  }, [person, nameInput, queryClient, id, setStats]);

  const handleIgnore = useCallback(async () => {
    if (!person) return;
    if (
      !window.confirm(
        `Hide ${personName(person)} (${person.photo_count} photos) from the people list?\n\n` +
          `The photos stay in your library. You can restore them under "Ignored people" on the People page.`
      )
    ) {
      return;
    }
    await api.ignorePerson(person.person_id);
    navigate("/people");
  }, [person, navigate]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  if (!person) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <p>Person not found</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
        <button
          onClick={() => navigate("/people")}
          className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>

        {person.face_thumbnail_url && (
          <img
            src={person.face_thumbnail_url}
            alt=""
            className="w-10 h-10 rounded-full object-cover"
          />
        )}

        {editingName ? (
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSaveName();
                if (e.key === "Escape") setEditingName(false);
              }}
              className="px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:border-primary-400"
              autoFocus
            />
            <button onClick={handleSaveName} className="p-1 hover:bg-gray-100 rounded">
              <Check className="w-4 h-4 text-green-600" />
            </button>
            <button onClick={() => setEditingName(false)} className="p-1 hover:bg-gray-100 rounded">
              <X className="w-4 h-4 text-gray-400" />
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold">
              {personName(person)}
            </h1>
            <button onClick={handleStartEdit} className="p-1 hover:bg-gray-100 rounded">
              <Pencil className="w-4 h-4 text-gray-400" />
            </button>
            <span className="text-sm text-gray-400">
              {person.photo_count} photo{person.photo_count !== 1 ? "s" : ""}
            </span>
          </div>
        )}

        <div className="ml-auto flex items-center gap-1">
          <CollageButton
            url={`/api/persons/${person.person_id}/collage`}
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
      </div>

      <PhotoGrid photos={photos} onPhotoClick={handlePhotoClick} />
    </div>
  );
}

// Together detail view (route: /people/together/...)
export function TogetherDetail() {
  const { personIds } = useParams<{ personIds: string }>();
  const navigate = useNavigate();
  const openPhoto = useOpenPhoto();
  const ids = (personIds ?? "").split(",").map(Number).filter(Boolean);
  const enabled = ids.length >= 2;

  const { data: personsData, isLoading: personsLoading } = useQuery({
    queryKey: ["persons-together", personIds],
    queryFn: () => Promise.all(ids.map((id) => api.getPerson(id))),
    enabled,
  });
  const { data: photosPage, isLoading: photosLoading } = useQuery({
    queryKey: ["shared-photos", personIds],
    queryFn: () => api.getSharedPhotosN(ids, { page_size: 200 }),
    enabled,
  });
  const persons = personsData ?? [];
  const photos = photosPage?.items ?? [];
  const loading = personsLoading || photosLoading;

  const handlePhotoClick = useCallback(
    (photo: PhotoSummary, index: number) => openPhoto(photo, index, photos),
    [openPhoto, photos]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
        <button
          onClick={() => navigate("/people")}
          className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex -space-x-2">
          {persons.map((p) => p.face_thumbnail_url && (
            <img key={p.person_id} src={p.face_thumbnail_url} alt="" className="w-8 h-8 rounded-full object-cover ring-2 ring-white" />
          ))}
        </div>
        <div>
          <h1 className="text-lg font-semibold">{groupNames(persons)}</h1>
          <span className="text-xs text-gray-400">{photos.length} shared photos</span>
        </div>
        {persons.length >= 2 && (
          <div className="ml-auto">
            <CollageButton
              url={`/api/persons/groups/together-n/collage?person_ids=${persons.map((p) => p.person_id).join(",")}`}
              label={`${groupNames(persons)} — Collage`}
              photoCount={photos.length}
            />
          </div>
        )}
      </div>
      <PhotoGrid photos={photos} onPhotoClick={handlePhotoClick} />
    </div>
  );
}

// People list view (route: /people)
export function People() {
  const [ignoredPersons, setIgnoredPersons] = useState<PersonSummary[]>([]);
  const [showIgnored, setShowIgnored] = useState(false);
  const [showHiddenGroups, setShowHiddenGroups] = useState(false);
  const navigate = useNavigate();
  const { scrollRef, restoreScroll } = useScrollRestore("people");
  const queryClient = useQueryClient();

  const { data: personsData, isLoading: loadingPersons } = useQuery({
    queryKey: ["persons"],
    queryFn: () => api.getPersons({ page_size: 200 }),
  });
  const { data: groupsData, isLoading: loadingGroups } = useQuery({
    queryKey: ["person-groups", { min_photos: 3 }],
    queryFn: () => api.getPersonGroups({ min_photos: 3 }),
  });
  const persons = personsData ?? [];
  const groups = groupsData ?? [];
  const { data: hiddenGroupsData } = useQuery({
    queryKey: ["hidden-groups"],
    queryFn: () => api.getHiddenGroups(),
  });
  const hiddenGroups = hiddenGroupsData ?? [];

  useEffect(() => {
    if (!loadingPersons && !loadingGroups && persons.length > 0) {
      restoreScroll();
    }
  }, [loadingPersons, loadingGroups, persons.length, restoreScroll]);

  const loadIgnored = useCallback(async () => {
    if (showIgnored) {
      setShowIgnored(false);
      return;
    }
    const data = await api.getIgnoredPersons();
    setIgnoredPersons(data);
    setShowIgnored(true);
  }, [showIgnored]);

  const handleIgnore = useCallback(async (e: React.MouseEvent, person: PersonSummary) => {
    e.stopPropagation();
    if (
      !window.confirm(
        `Hide ${personName(person)} (${person.photo_count} photos) from the people list?\n\n` +
          `The photos stay in your library. You can restore them under "Ignored people" below.`
      )
    ) {
      return;
    }
    await api.ignorePerson(person.person_id);
    queryClient.invalidateQueries({ queryKey: ["persons"] });
    if (showIgnored) {
      const data = await api.getIgnoredPersons();
      setIgnoredPersons(data);
    }
  }, [showIgnored, queryClient]);

  const handleUnignore = useCallback(async (personId: number) => {
    await api.unignorePerson(personId);
    setIgnoredPersons((prev) => prev.filter((p) => p.person_id !== personId));
    // Reload main list
    queryClient.invalidateQueries({ queryKey: ["persons"] });
  }, [queryClient]);

  // Together tiles: hiding removes just that tile from the section — the
  // people themselves stay visible on the page and in their photos.
  const handleHideGroup = useCallback(async (personIds: number[]) => {
    await api.hideGroup(personIds);
    queryClient.invalidateQueries({ queryKey: ["person-groups"] });
    queryClient.invalidateQueries({ queryKey: ["hidden-groups"] });
  }, [queryClient]);

  const handleUnhideGroup = useCallback(async (personIds: number[]) => {
    await api.unhideGroup(personIds);
    queryClient.invalidateQueries({ queryKey: ["hidden-groups"] });
    queryClient.invalidateQueries({ queryKey: ["person-groups"] });
  }, [queryClient]);

  if (loadingPersons) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  if (persons.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
        <Users className="w-12 h-12 text-gray-300" />
        <p className="text-lg">No people detected yet</p>
        <p className="text-sm">Face detection will run during photo processing</p>
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100">
        <h1 className="text-lg font-semibold">
          People
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {persons.length} person{persons.length !== 1 ? "s" : ""}
          </span>
        </h1>
      </div>

      {/* Together section — on top */}
      {(loadingGroups || groups.length > 0 || hiddenGroups.length > 0) && (
        <>
          <div className="px-4 py-3 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-700">
              Together
              {!loadingGroups && (
                <span className="ml-2 text-gray-400 font-normal text-sm">
                  {groups.length} group{groups.length !== 1 ? "s" : ""}
                </span>
              )}
            </h2>
          </div>

          {loadingGroups ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 p-4">
              {[0, 1, 2].map((i) => (
                <div key={i} className="rounded-xl overflow-hidden border border-gray-100">
                  <div className="aspect-video bg-gray-100 animate-pulse" />
                  <div className="p-3 flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-gray-100 animate-pulse" />
                    <div className="flex-1 space-y-1.5">
                      <div className="h-3.5 bg-gray-100 rounded animate-pulse w-3/4" />
                      <div className="h-3 bg-gray-100 rounded animate-pulse w-1/2" />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 p-4">
              {groups.map((group, i) => {
                if (group.persons.length < 2) return null;
                const ids = group.persons.map((p) => p.person_id).join(",");
                return (
                  <div key={i} className="relative group">
                    <button
                      onClick={() => navigate(`/people/together/${ids}`)}
                      className="w-full bg-white rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow border border-gray-100 text-left"
                    >
                      <div className="aspect-video bg-gray-100 relative overflow-hidden">
                        {group.cover_photo ? (
                          <img
                            src={thumbnailUrl(group.cover_photo.file_hash, 600)}
                            alt=""
                            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                          />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center">
                            <Users className="w-12 h-12 text-gray-300" />
                          </div>
                        )}
                      </div>
                      <div className="p-3 flex items-center gap-3">
                        <div className="flex -space-x-2">
                          {group.persons.map((p) => p.face_thumbnail_url && (
                            <img key={p.person_id} src={p.face_thumbnail_url} alt="" className="w-8 h-8 rounded-full object-cover ring-2 ring-white" />
                          ))}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium truncate">
                            {groupNames(group.persons)}
                          </p>
                          <p className="text-xs text-gray-400">{group.shared_photo_count} photos together</p>
                        </div>
                      </div>
                    </button>
                    {/* Sits outside the nav button: button-in-button is invalid HTML */}
                    <button
                      onClick={() => handleHideGroup(group.persons.map((p) => p.person_id))}
                      className="absolute top-2 right-2 p-1.5 rounded-full bg-white/90 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity hover:bg-white shadow-sm"
                      title="Hide this group"
                    >
                      <X className="w-4 h-4 text-gray-500" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {/* Hidden tiles — restore row */}
          {hiddenGroups.length > 0 && (
            <div className="px-4 pb-4">
              <button
                onClick={() => setShowHiddenGroups((v) => !v)}
                className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-gray-600 transition-colors"
              >
                <EyeOff className="w-4 h-4" />
                {hiddenGroups.length} hidden group{hiddenGroups.length !== 1 ? "s" : ""}
                <ChevronDown className={`w-4 h-4 transition-transform ${showHiddenGroups ? "rotate-180" : ""}`} />
              </button>
              {showHiddenGroups && (
                <div className="flex flex-wrap gap-2 mt-3">
                  {hiddenGroups.map((g) => (
                    <div key={g.group_key} className="flex items-center gap-2 pl-1.5 pr-2 py-1 rounded-full border border-gray-200 bg-white">
                      <div className="flex -space-x-1.5">
                        {g.persons.map((p) => p.face_thumbnail_url && (
                          <img key={p.person_id} src={p.face_thumbnail_url} alt="" className="w-6 h-6 rounded-full object-cover ring-1 ring-white" />
                        ))}
                      </div>
                      <span className="text-xs text-gray-600">
                        {g.persons.length ? groupNames(g.persons) : g.group_key}
                      </span>
                      <button
                        onClick={() => handleUnhideGroup(g.persons.map((p) => p.person_id))}
                        className="p-0.5 rounded-full hover:bg-gray-100 transition-colors"
                        title="Show this group again"
                      >
                        <Eye className="w-3.5 h-3.5 text-gray-400" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* All people */}
      <div className="px-4 py-3 border-t border-b border-gray-100">
        <h2 className="text-base font-semibold text-gray-700">
          All People
        </h2>
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-4 p-4">
        {/* Cards are divs, not <button>s: the Ignore button nests inside, and button-in-button is invalid HTML */}
        {persons.map((person) => (
          <div
            key={person.person_id}
            role="button"
            tabIndex={0}
            onClick={() => navigate(`/people/${person.person_id}`)}
            onKeyDown={(e) => {
              if (e.key === "Enter") navigate(`/people/${person.person_id}`);
            }}
            className="flex flex-col items-center gap-2 p-3 rounded-xl hover:bg-gray-50 transition-colors group relative cursor-pointer"
          >
            {person.face_thumbnail_url ? (
              <img
                src={person.face_thumbnail_url}
                alt={person.name || ""}
                className="w-20 h-20 rounded-full object-cover group-hover:ring-2 ring-primary-300 transition-all"
              />
            ) : (
              <div className="w-20 h-20 rounded-full bg-gray-200 flex items-center justify-center">
                <Users className="w-8 h-8 text-gray-400" />
              </div>
            )}
            <div className="text-center">
              <p className="text-sm font-medium truncate max-w-[100px]">
                {personName(person)}
              </p>
              <p className="text-xs text-gray-400">{person.photo_count} photos</p>
            </div>
            <button
              onClick={(e) => handleIgnore(e, person)}
              className="absolute top-1 right-1 p-1 rounded-full bg-white/80 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-gray-200"
              title="Ignore"
            >
              <EyeOff className="w-3 h-3 text-gray-400" />
            </button>
          </div>
        ))}
      </div>

      {/* Ignored section */}
      <div className="border-t border-gray-100">
        <button
          onClick={loadIgnored}
          className="w-full px-4 py-3 flex items-center gap-2 text-sm text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors"
        >
          <EyeOff className="w-4 h-4" />
          Ignored people
          <ChevronDown className={`w-4 h-4 ml-auto transition-transform ${showIgnored ? "rotate-180" : ""}`} />
        </button>

        {showIgnored && ignoredPersons.length > 0 && (
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-4 px-4 pb-4">
            {ignoredPersons.map((person) => (
              <div
                key={person.person_id}
                className="flex flex-col items-center gap-2 p-3 rounded-xl opacity-50 hover:opacity-100 transition-opacity relative group"
              >
                {person.face_thumbnail_url ? (
                  <img
                    src={person.face_thumbnail_url}
                    alt=""
                    className="w-20 h-20 rounded-full object-cover grayscale"
                  />
                ) : (
                  <div className="w-20 h-20 rounded-full bg-gray-200 flex items-center justify-center">
                    <Users className="w-8 h-8 text-gray-400" />
                  </div>
                )}
                <div className="text-center">
                  <p className="text-sm font-medium truncate max-w-[100px] text-gray-400">
                    {personName(person)}
                  </p>
                  <p className="text-xs text-gray-300">{person.photo_count} photos</p>
                </div>
                <button
                  onClick={() => handleUnignore(person.person_id)}
                  className="absolute top-1 right-1 p-1 rounded-full bg-white/80 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-gray-200"
                  title="Un-ignore"
                >
                  <Eye className="w-3 h-3 text-gray-500" />
                </button>
              </div>
            ))}
          </div>
        )}
        {showIgnored && ignoredPersons.length === 0 && (
          <p className="px-4 pb-4 text-sm text-gray-300">No ignored people</p>
        )}
      </div>
    </div>
  );
}
