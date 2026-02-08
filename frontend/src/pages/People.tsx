import { useEffect, useState, useCallback } from "react";
import { api, type PersonSummary, type PhotoSummary } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { Loader2, Users, ArrowLeft, Pencil, Check, X } from "lucide-react";

export function People() {
  const [persons, setPersons] = useState<PersonSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPerson, setSelectedPerson] = useState<PersonSummary | null>(null);
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [photosLoading, setPhotosLoading] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [nameInput, setNameInput] = useState("");
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const data = await api.getPersons({ page_size: 200 });
        setPersons(data);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const handleSelectPerson = useCallback(async (person: PersonSummary) => {
    setSelectedPerson(person);
    setPhotosLoading(true);
    try {
      const data = await api.getPersonPhotos(person.person_id, { page_size: 200 });
      setPhotos(data.items);
    } catch {
      // ignore
    } finally {
      setPhotosLoading(false);
    }
  }, []);

  const handleBack = useCallback(() => {
    setSelectedPerson(null);
    setPhotos([]);
    setEditingName(false);
  }, []);

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
        openViewer(detail);
      } catch {
        // ignore
      }
    },
    [openViewer]
  );

  const handleStartEdit = useCallback(() => {
    if (selectedPerson) {
      setNameInput(selectedPerson.name || "");
      setEditingName(true);
    }
  }, [selectedPerson]);

  const handleSaveName = useCallback(async () => {
    if (!selectedPerson || !nameInput.trim()) return;
    try {
      const updated = await api.updatePerson(selectedPerson.person_id, nameInput.trim());
      setSelectedPerson(updated);
      setPersons((prev) =>
        prev.map((p) => (p.person_id === updated.person_id ? updated : p))
      );
      setEditingName(false);
    } catch {
      // ignore
    }
  }, [selectedPerson, nameInput]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  // Person detail view
  if (selectedPerson) {
    return (
      <div className="overflow-y-auto h-full">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
          <button
            onClick={handleBack}
            className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>

          {selectedPerson.face_thumbnail_url && (
            <img
              src={selectedPerson.face_thumbnail_url}
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
                {selectedPerson.name || `Person ${selectedPerson.person_id}`}
              </h1>
              <button onClick={handleStartEdit} className="p-1 hover:bg-gray-100 rounded">
                <Pencil className="w-4 h-4 text-gray-400" />
              </button>
              <span className="text-sm text-gray-400">
                {selectedPerson.photo_count} photo{selectedPerson.photo_count !== 1 ? "s" : ""}
              </span>
            </div>
          )}
        </div>

        {photosLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
          </div>
        ) : (
          <PhotoGrid photos={photos} onPhotoClick={handlePhotoClick} />
        )}
      </div>
    );
  }

  // Person grid
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
    <div className="overflow-y-auto h-full">
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
            onClick={() => handleSelectPerson(person)}
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
    </div>
  );
}
