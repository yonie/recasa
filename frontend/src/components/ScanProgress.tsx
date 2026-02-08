import { Loader2 } from "lucide-react";
import { useStore } from "../store/useStore";

export function ScanProgress() {
  const scanStatus = useStore((s) => s.scanStatus);

  if (!scanStatus?.is_scanning) return null;

  const progress =
    scanStatus.total_files > 0
      ? Math.round((scanStatus.processed_files / scanStatus.total_files) * 100)
      : 0;

  return (
    <div className="flex items-center gap-2 text-sm text-gray-500">
      <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
      <span className="hidden sm:inline">
        {scanStatus.phase === "discovery" && "Scanning files..."}
        {scanStatus.phase === "exif" && "Extracting metadata..."}
        {scanStatus.phase === "geocoding" && "Geocoding locations..."}
        {scanStatus.phase === "thumbnails" && "Generating thumbnails..."}
        {scanStatus.phase === "hashing" && "Computing hashes..."}
        {!scanStatus.phase && "Processing..."}
      </span>
      {scanStatus.total_files > 0 && (
        <div className="flex items-center gap-2">
          <div className="w-20 h-1.5 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-primary-500 rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="text-xs tabular-nums">{progress}%</span>
        </div>
      )}
    </div>
  );
}
