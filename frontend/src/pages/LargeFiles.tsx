import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { HardDrive } from "lucide-react";
import { clsx } from "clsx";
import { api, thumbnailUrl } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { EmptyState, ErrorState, PageHeader, PageSpinner, PageTitle } from "../components/Page";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { formatBytes, plural } from "../lib/format";

const SIZE_OPTIONS = [
  { label: "> 1 MB", value: 1_000_000 },
  { label: "> 5 MB", value: 5_000_000 },
  { label: "> 10 MB", value: 10_000_000 },
  { label: "> 25 MB", value: 25_000_000 },
  { label: "> 50 MB", value: 50_000_000 },
];

export function LargeFiles() {
  const [minSize, setMinSize] = useState(10_000_000);
  const openPhoto = useOpenPhoto();

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.largeFiles(minSize),
    queryFn: () => api.getLargeFiles({ min_size: minSize, page_size: 100 }),
  });
  const photos = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="overflow-y-auto h-full">
      <PageHeader className="flex items-center justify-between">
        <PageTitle count={`${total} ${plural(total, "photo")}`}>Large Files</PageTitle>

        <div className="flex items-center gap-2">
          {SIZE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setMinSize(opt.value)}
              className={clsx(
                "px-3 py-1 text-xs rounded-full border transition-colors",
                minSize === opt.value
                  ? "bg-primary-50 border-primary-200 text-primary-700"
                  : "border-gray-200 text-gray-500 hover:bg-gray-50"
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </PageHeader>

      {isLoading ? (
        <PageSpinner />
      ) : error ? (
        <ErrorState error={error} />
      ) : photos.length === 0 ? (
        <EmptyState icon={HardDrive} title="No large files found" />
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
              {photos.map((photo, index) => (
                <tr
                  key={photo.file_hash}
                  className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer"
                  onClick={() => openPhoto(photo, index, photos)}
                >
                  <td className="py-2 pr-3">
                    <img
                      src={thumbnailUrl(photo.file_hash, 200)}
                      alt={photo.file_name}
                      loading="lazy"
                      decoding="async"
                      className="w-12 h-12 object-cover rounded"
                    />
                  </td>
                  <td className="py-2">
                    <p className="font-medium text-gray-700">{photo.file_name}</p>
                    <p className="text-xs text-gray-400">{photo.file_path}</p>
                  </td>
                  <td className="py-2 text-gray-600 font-mono">{formatBytes(photo.file_size)}</td>
                  <td className="py-2 text-gray-500">
                    {photo.width && photo.height ? `${photo.width} x ${photo.height}` : "-"}
                  </td>
                  <td className="py-2 text-gray-500">
                    {photo.date_taken ? new Date(photo.date_taken).toLocaleDateString() : "-"}
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
