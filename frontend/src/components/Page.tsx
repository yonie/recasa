/**
 * Building blocks every page uses: loading, empty and error states, the
 * header bar, and the "header above a photo grid" layout most routes share.
 */
import type { ComponentType, ReactNode } from "react";
import { AlertCircle, ArrowLeft, Loader2 } from "lucide-react";
import { clsx } from "clsx";
import type { PhotoSummary } from "../api/client";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { PhotoGrid } from "./PhotoGrid";

export function PageSpinner() {
  return (
    <div className="flex items-center justify-center h-64">
      <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  hint,
}: {
  icon?: ComponentType<{ className?: string }>;
  title: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
      {Icon && <Icon className="w-12 h-12 text-gray-300" />}
      <p className="text-lg">{title}</p>
      {hint && <p className="text-sm">{hint}</p>}
    </div>
  );
}

/** A failed load, instead of an empty state that would claim there is nothing. */
export function ErrorState({ error }: { error: unknown }) {
  return (
    <div className="flex flex-col items-center justify-center h-64 text-red-500 gap-2">
      <AlertCircle className="w-8 h-8" />
      <p>{error instanceof Error ? error.message : "Failed to load"}</p>
    </div>
  );
}

/** The bar at the top of a page. Pass layout classes (flex, gap...) as needed. */
export function PageHeader({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("px-4 py-3 border-b border-gray-100", className)}>{children}</div>;
}

/** Page title with an optional muted count after it ("Favorites 12 photos"). */
export function PageTitle({ children, count }: { children: ReactNode; count?: ReactNode }) {
  return (
    <h1 className="text-lg font-semibold">
      {children}
      {count !== undefined && (
        <span className="ml-2 text-gray-400 font-normal text-sm">{count}</span>
      )}
    </h1>
  );
}

export function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors">
      <ArrowLeft className="w-5 h-5" />
    </button>
  );
}

/** A scrolling page: header, then the photos as a grid that opens the viewer. */
export function PhotoListLayout({ header, photos }: { header: ReactNode; photos: PhotoSummary[] }) {
  const openPhoto = useOpenPhoto();
  return (
    <div className="overflow-y-auto h-full">
      {header}
      <PhotoGrid photos={photos} onPhotoClick={openPhoto} />
    </div>
  );
}
