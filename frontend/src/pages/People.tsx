import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, type PersonSummary, type PersonGroup, type PhotoSummary, thumbnailUrl } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { useScrollRestore } from "../hooks/useScrollRestore";
import { Loader2, Users, ArrowLeft, Pencil, Check, X, EyeOff, Eye, ChevronDown } from "lucide-react";

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
  const [person, setPerson] = useState<PersonSummary | null>(null);
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingName, setEditingName] = useState(false);
  const [nameInput, setNameInput] = useState("");
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      if (!personId) return;
      try {
        setLoading(true);
        const [personData, photosData] = await Promise.all([
          api.getPerson(Number(personId)),
          api.getPersonPhotos(Number(personId), { page_size: 200 }),
        ]);
        setPerson(personData);
        setPhotos(photosData.items);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [personId]);

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary, index: number) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
        openViewer(detail, photos, index);
      } catch {
        // ignore
      }
    },
    [openViewer, photos]
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
      setPerson(updated);
      setEditingName(false);
    } catch {
      // ignore
    }
  }, [person, nameInput]);

  const handleIgnore = useCallback(async () => {
    if (!person) return;
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

        <button
          onClick={handleIgnore}
          className="ml-auto p-1.5 rounded-lg hover:bg-gray-100 transition-colors text-gray-400 hover:text-gray-600"
          title="Ignore this person"
        >
          <EyeOff className="w-4 h-4" />
        </button>
      </div>

      <PhotoGrid photos={photos} onPhotoClick={handlePhotoClick} />
    </div>
  );
}

// Together detail view (route: /people/together/...)
export function TogetherDetail() {
  const { personIds } = useParams<{ personIds: string }>();
  const navigate = useNavigate();
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [persons, setPersons] = useState<PersonSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      if (!personIds) return;
      const ids = personIds.split(",").map(Number).filter(Boolean);
      if (ids.length < 2) return;
      try {
        setLoading(true);
        // Fetch all persons in parallel
        const personPromises = ids.map((id) => api.getPerson(id));
        const personsData = await Promise.all(personPromises);
        setPersons(personsData);
        // For shared photos, use first two person IDs (API supports pairs)
        const photosData = await api.getSharedPhotos(ids[0]!, ids[1]!, { page_size: 200 });
        setPhotos(photosData.items);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [personIds]);

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary, index: number) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
        openViewer(detail, photos, index);
      } catch {
        // ignore
      }
    },
    [openViewer, photos]
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
      </div>
      <PhotoGrid photos={photos} onPhotoClick={handlePhotoClick} />
    </div>
  );
}

// People list view (route: /people)
export function People() {
  const [persons, setPersons] = useState<PersonSummary[]>([]);
  const [groups, setGroups] = useState<PersonGroup[]>([]);
  const [ignoredPersons, setIgnoredPersons] = useState<PersonSummary[]>([]);
  const [showIgnored, setShowIgnored] = useState(false);
  const [loadingPersons, setLoadingPersons] = useState(true);
  const [loadingGroups, setLoadingGroups] = useState(true);
  const navigate = useNavigate();
  const { scrollRef, restoreScroll } = useScrollRestore("people");

  const loadAll = useCallback(() => {
    setLoadingPersons(true);
    setLoadingGroups(true);

    api.getPersons({ page_size: 200 })
      .then(setPersons)
      .catch(() => {})
      .finally(() => setLoadingPersons(false));

    api.getPersonGroups({ min_photos: 3 })
      .then(setGroups)
      .catch(() => {})
      .finally(() => setLoadingGroups(false));
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  useEffect(() => {
    if (!loadingPersons && persons.length > 0) {
      restoreScroll();
    }
  }, [loadingPersons, persons.length, restoreScroll]);

  const loadIgnored = useCallback(async () => {
    if (showIgnored) {
      setShowIgnored(false);
      return;
    }
    const data = await api.getIgnoredPersons();
    setIgnoredPersons(data);
    setShowIgnored(true);
  }, [showIgnored]);

  const handleIgnore = useCallback(async (e: React.MouseEvent, personId: number) => {
    e.stopPropagation();
    await api.ignorePerson(personId);
    setPersons((prev) => prev.filter((p) => p.person_id !== personId));
    if (showIgnored) {
      const data = await api.getIgnoredPersons();
      setIgnoredPersons(data);
    }
  }, [showIgnored]);

  const handleUnignore = useCallback(async (personId: number) => {
    await api.unignorePerson(personId);
    setIgnoredPersons((prev) => prev.filter((p) => p.person_id !== personId));
    // Reload main list
    api.getPersons({ page_size: 200 }).then(setPersons).catch(() => {});
  }, []);

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
      {loadingGroups && (
        <div className="flex items-center gap-2 px-4 py-6 text-gray-400 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading together albums...
        </div>
      )}
      {!loadingGroups && groups.length > 0 && (
        <>
          <div className="px-4 py-3 border-b border-gray-100">
            <h2 className="text-base font-semibold text-gray-700">
              Together
              <span className="ml-2 text-gray-400 font-normal text-sm">
                {groups.length} group{groups.length !== 1 ? "s" : ""}
              </span>
            </h2>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 p-4">
            {groups.map((group, i) => {
              if (group.persons.length < 2) return null;
              const ids = group.persons.map((p) => p.person_id).join(",");
              return (
                <button
                  key={i}
                  onClick={() => navigate(`/people/together/${ids}`)}
                  className="bg-white rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow border border-gray-100 text-left group"
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
              );
            })}
          </div>
        </>
      )}

      {/* All people */}
      <div className="px-4 py-3 border-t border-b border-gray-100">
        <h2 className="text-base font-semibold text-gray-700">
          All People
        </h2>
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-4 p-4">
        {persons.map((person) => (
          <button
            key={person.person_id}
            onClick={() => navigate(`/people/${person.person_id}`)}
            className="flex flex-col items-center gap-2 p-3 rounded-xl hover:bg-gray-50 transition-colors group relative"
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
              onClick={(e) => handleIgnore(e, person.person_id)}
              className="absolute top-1 right-1 p-1 rounded-full bg-white/80 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-gray-200"
              title="Ignore"
            >
              <EyeOff className="w-3 h-3 text-gray-400" />
            </button>
          </button>
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
