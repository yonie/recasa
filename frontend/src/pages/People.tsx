import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api, type PersonSummary, type PersonGroup, type PhotoSummary, thumbnailUrl } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { useScrollRestore } from "../hooks/useScrollRestore";
import { Loader2, Users, ArrowLeft, Pencil, Check, X } from "lucide-react";

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
              {person.name || `Person ${person.person_id}`}
            </h1>
            <button onClick={handleStartEdit} className="p-1 hover:bg-gray-100 rounded">
              <Pencil className="w-4 h-4 text-gray-400" />
            </button>
            <span className="text-sm text-gray-400">
              {person.photo_count} photo{person.photo_count !== 1 ? "s" : ""}
            </span>
          </div>
        )}
      </div>

      <PhotoGrid photos={photos} onPhotoClick={handlePhotoClick} />
    </div>
  );
}

// Together detail view (route: /people/together/:personAId/:personBId)
export function TogetherDetail() {
  const { personAId, personBId } = useParams<{ personAId: string; personBId: string }>();
  const navigate = useNavigate();
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [personA, setPersonA] = useState<PersonSummary | null>(null);
  const [personB, setPersonB] = useState<PersonSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      if (!personAId || !personBId) return;
      try {
        setLoading(true);
        const [a, b, photosData] = await Promise.all([
          api.getPerson(Number(personAId)),
          api.getPerson(Number(personBId)),
          api.getSharedPhotos(Number(personAId), Number(personBId), { page_size: 200 }),
        ]);
        setPersonA(a);
        setPersonB(b);
        setPhotos(photosData.items);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [personAId, personBId]);

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

  const nameA = personA?.name || `Person ${personAId}`;
  const nameB = personB?.name || `Person ${personBId}`;

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
        <button
          onClick={() => navigate("/people")}
          className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex items-center gap-2">
          {personA?.face_thumbnail_url && (
            <img src={personA.face_thumbnail_url} alt="" className="w-8 h-8 rounded-full object-cover" />
          )}
          {personB?.face_thumbnail_url && (
            <img src={personB.face_thumbnail_url} alt="" className="w-8 h-8 rounded-full object-cover -ml-3 ring-2 ring-white" />
          )}
        </div>
        <div>
          <h1 className="text-lg font-semibold">{nameA} & {nameB}</h1>
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
  const [loadingPersons, setLoadingPersons] = useState(true);
  const [loadingGroups, setLoadingGroups] = useState(true);
  const navigate = useNavigate();
  const { scrollRef, restoreScroll } = useScrollRestore("people");

  // Load persons (fast) and groups (slower) independently
  useEffect(() => {
    api.getPersons({ page_size: 200 })
      .then(setPersons)
      .catch(() => {})
      .finally(() => setLoadingPersons(false));

    api.getPersonGroups({ min_photos: 3 })
      .then(setGroups)
      .catch(() => {})
      .finally(() => setLoadingGroups(false));
  }, []);

  useEffect(() => {
    if (!loadingPersons && persons.length > 0) {
      restoreScroll();
    }
  }, [loadingPersons, persons.length, restoreScroll]);

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

      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 gap-4 p-4">
        {persons.map((person) => (
          <button
            key={person.person_id}
            onClick={() => navigate(`/people/${person.person_id}`)}
            className="flex flex-col items-center gap-2 p-3 rounded-xl hover:bg-gray-50 transition-colors group"
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
                {person.name || `Person ${person.person_id}`}
              </p>
              <p className="text-xs text-gray-400">{person.photo_count} photos</p>
            </div>
          </button>
        ))}
      </div>

      {/* Together section */}
      {loadingGroups && (
        <div className="flex items-center gap-2 px-4 py-6 border-t border-gray-100 text-gray-400 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading together albums...
        </div>
      )}
      {!loadingGroups && groups.length > 0 && (
        <>
          <div className="px-4 py-3 border-t border-b border-gray-100">
            <h2 className="text-lg font-semibold">
              Together
              <span className="ml-2 text-gray-400 font-normal text-sm">
                {groups.length} pair{groups.length !== 1 ? "s" : ""}
              </span>
            </h2>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 p-4">
            {groups.map((group, i) => {
              const a = group.persons[0];
              const b = group.persons[1];
              if (!a || !b) return null;
              return (
                <button
                  key={i}
                  onClick={() => navigate(`/people/together/${a.person_id}/${b.person_id}`)}
                  className="bg-white rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow border border-gray-100 text-left group"
                >
                  {/* Cover photo */}
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
                  {/* Info */}
                  <div className="p-3 flex items-center gap-3">
                    <div className="flex -space-x-2">
                      {a.face_thumbnail_url && (
                        <img src={a.face_thumbnail_url} alt="" className="w-8 h-8 rounded-full object-cover ring-2 ring-white" />
                      )}
                      {b.face_thumbnail_url && (
                        <img src={b.face_thumbnail_url} alt="" className="w-8 h-8 rounded-full object-cover ring-2 ring-white" />
                      )}
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">
                        {a.name || `Person ${a.person_id}`} & {b.name || `Person ${b.person_id}`}
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
    </div>
  );
}
