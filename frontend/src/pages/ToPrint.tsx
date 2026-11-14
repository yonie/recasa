import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, ListX, Loader2, Printer } from "lucide-react";
import { clsx } from "clsx";
import { api, printExportUrl, thumbnailUrl, type PhotoSummary } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { GridViewControls } from "../components/GridViewControls";
import { EmptyState, ErrorState, PageHeader, PageSpinner, PageTitle } from "../components/Page";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { usePhotoActions } from "../hooks/usePhotoActions";
import { formatBytes, plural } from "../lib/format";
import { isLowRes, printFormatLabel, printQuality } from "../lib/printQuality";
import { useStore, type GridSize } from "../store/useStore";

const CARD_GRID_CLASSES: Record<GridSize, string> = {
  S: "grid-cols-3 sm:grid-cols-4 md:grid-cols-5 xl:grid-cols-6",
  M: "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5",
  L: "grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-3",
};

export function ToPrint() {
  const [clearing, setClearing] = useState(false);
  const openPhoto = useOpenPhoto();
  const { togglePrint, clearPrintList } = usePhotoActions();
  const gridSize = useStore((s) => s.gridSize);

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.photoList({ marked_for_print: true }),
    queryFn: () => api.getPhotos({ marked_for_print: true, page_size: 200 }),
  });
  const photos = data?.items ?? [];

  const handleRemoveAll = async () => {
    const count = photos.length;
    if (
      !window.confirm(
        `Remove all ${count} ${plural(count, "photo")} from the To Print list? ` +
          "Your photos are not deleted."
      )
    ) {
      return;
    }
    setClearing(true);
    try {
      await clearPrintList();
    } catch {
      // The list stays as it was.
    } finally {
      setClearing(false);
    }
  };

  if (isLoading) return <PageSpinner />;
  if (error) return <ErrorState error={error} />;
  if (photos.length === 0) {
    return (
      <EmptyState
        icon={Printer}
        title="Nothing to print yet"
        hint="Hover over photos and click the printer icon, or press P while viewing"
      />
    );
  }

  const lowResCount = photos.filter(isLowRes).length;

  return (
    <div className="overflow-y-auto h-full">
      <PageHeader className="flex flex-wrap items-center gap-3">
        <PageTitle count={`${photos.length} ${plural(photos.length, "photo")}`}>To Print</PageTitle>
        {lowResCount > 0 && (
          <span className="text-xs text-amber-600 bg-amber-50 px-2 py-1 rounded-full">
            {lowResCount} {plural(lowResCount, "photo")} may be too small to print well
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <a
            href={printExportUrl()}
            download
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary-600 text-white
                       text-sm font-medium hover:bg-primary-700 transition-colors"
          >
            <Download className="w-4 h-4" />
            Download zip
          </a>
          <button
            onClick={handleRemoveAll}
            disabled={clearing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200
                       text-sm text-gray-600 hover:bg-gray-100 transition-colors disabled:opacity-50"
          >
            {clearing ? <Loader2 className="w-4 h-4 animate-spin" /> : <ListX className="w-4 h-4" />}
            Remove all from list
          </button>
        </div>
      </PageHeader>

      <div className={clsx("grid gap-4 p-4", CARD_GRID_CLASSES[gridSize])}>
        {photos.map((photo, index) => (
          <PrintCard
            key={photo.file_hash}
            photo={photo}
            onClick={() => openPhoto(photo, index, photos)}
            onRemove={() => togglePrint(photo.file_hash).catch(() => {})}
          />
        ))}
      </div>
      <GridViewControls />
    </div>
  );
}

interface PrintCardProps {
  photo: PhotoSummary;
  onClick: () => void;
  onRemove: () => void;
}

function PrintCard({ photo, onClick, onRemove }: PrintCardProps) {
  const gridFit = useStore((s) => s.gridFit);
  const { width, height } = photo;
  const quality = width && height ? printQuality(width, height) : null;

  return (
    <div className="rounded-lg border border-gray-200 bg-white overflow-hidden group">
      <div className="relative aspect-square bg-gray-100 cursor-pointer" onClick={onClick}>
        <img
          src={thumbnailUrl(photo.file_hash, 600)}
          alt={photo.file_name}
          loading="lazy"
          className={clsx("w-full h-full", gridFit === "square" ? "object-cover" : "object-contain")}
        />
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="absolute top-2 right-2 p-1.5 rounded-full bg-black/40 text-white
                     opacity-100 sm:opacity-0 sm:group-hover:opacity-100
                     hover:bg-black/60 transition-all"
          title="Remove from list"
        >
          <Printer className="w-4 h-4 fill-sky-400 text-sky-400" />
        </button>
      </div>

      <div className="p-2.5 space-y-1 text-xs">
        <p className="font-medium text-gray-700 truncate" title={photo.file_name}>
          {photo.file_name}
        </p>
        <p className="text-gray-500">
          {width && height ? (
            <>
              {width} × {height} · {((width * height) / 1_000_000).toFixed(1)} MP
            </>
          ) : (
            "Resolution unknown"
          )}
        </p>
        <p className="text-gray-500">
          {formatBytes(photo.file_size)} · {printFormatLabel(photo.mime_type, photo.file_name)}
        </p>
        {quality && (
          <p
            className={clsx(
              "font-medium",
              quality.level === "good" && "text-green-600",
              quality.level === "borderline" && "text-amber-600",
              quality.level === "poor" && "text-red-600"
            )}
          >
            {quality.dpiAt10x15} DPI at 10×15
            {quality.level === "good" && quality.maxGoodSize && (
              <> · good up to {quality.maxGoodSize[0]}×{quality.maxGoodSize[1]} cm</>
            )}
            {quality.level === "borderline" && <> · borderline for printing</>}
            {quality.level === "poor" && <> · too small to print well</>}
          </p>
        )}
      </div>
    </div>
  );
}
