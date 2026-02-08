import { useEffect, useState, useCallback } from "react";
import { api, type PhotoSummary } from "../api/client";
import { useStore } from "../store/useStore";
import { thumbnailUrl } from "../api/client";
import { Loader2, HardDrive } from "lucide-react";

const SIZE_OPTIONS = [
  { label: "> 1 MB", value: 1_000_000 },
  { label: "> 5 MB", value: 5_000_000 },
  { label: "> 10 MB", value: 10_000_000 },
  { label: "> 25 MB", value: 25_000_000 },
  { label: "> 50 MB", value: 50_000_000 },
];

export function LargeFiles() {
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [minSize, setMinSize] = useState(10_000_000);
  const [loading, setLoading] = useState(true);
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const data = await api.getLargeFiles({ min_size: minSize, page_size: 100 });
        setPhotos(data.items);
        setTotal(data.total);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [minSize]);

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
        const index = photos.findIndex((p) => p.file_hash === photo.file_hash);
        openViewer(detail, photos, index);
      } catch {
        // ignore
      }
    },
    [openViewer, photos]
  );

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
        <h1 className="text-lg font-semibold">
          Large Files
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {total} photo{total !== 1 ? "s" : ""}
          </span>
        </h1>

        <div className="flex items-center gap-2">
          {SIZE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setMinSize(opt.value)}
              className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                minSize === opt.value
                  ? "bg-primary-50 border-primary-200 text-primary-700"
                  : "border-gray-200 text-gray-500 hover:bg-gray-50"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
        </div>
      ) : photos.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
          <HardDrive className="w-12 h-12 text-gray-300" />
          <p className="text-lg">No large files found</p>
        </div>
      ) : (
        <div className="p-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b">
                <th className="pb-2 font-medium">Preview</th>
                <th className="pb-2 font-medium">Filename</th>
                <th className="pb-2 font-medium">Size</th>
                <th className="pb-2 font-medium">Dimensions</th>
                <th className="pb-2 font-medium">Date</th>
              </tr>
            </thead>
            <tbody>
              {photos.map((photo) => (
                <tr
                  key={photo.file_hash}
                  className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer"
                  onClick={() => handlePhotoClick(photo)}
                >
                  <td className="py-2 pr-3">
                    <img
                      src={thumbnailUrl(photo.file_hash, 200)}
                      alt={photo.file_name}
                      className="w-12 h-12 object-cover rounded"
                    />
                  </td>
                  <td className="py-2">
                    <p className="font-medium text-gray-700">{photo.file_name}</p>
                    <p className="text-xs text-gray-400">{photo.file_path}</p>
                  </td>
                  <td className="py-2 text-gray-600 font-mono">
                    {formatBytes(photo.file_size)}
                  </td>
                  <td className="py-2 text-gray-500">
                    {photo.width && photo.height
                      ? `${photo.width} x ${photo.height}`
                      : "-"}
                  </td>
                  <td className="py-2 text-gray-500">
                    {photo.date_taken
                      ? new Date(photo.date_taken).toLocaleDateString()
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}
