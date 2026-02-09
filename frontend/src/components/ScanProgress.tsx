import { Loader2 } from "lucide-react";
import { useStore } from "../store/useStore";

export function ScanProgress() {
  const scanStatus = useStore((s) => s.scanStatus);

  if (!scanStatus?.is_scanning) return null;

  const overallProgress =
    scanStatus.total_files > 0
      ? Math.round((scanStatus.processed_files / scanStatus.total_files) * 100)
      : 0;

  const phaseProgress =
    scanStatus.phase_total > 0
      ? Math.round((scanStatus.phase_progress / scanStatus.phase_total) * 100)
      : 0;

  const getPhaseInfo = () => {
    switch (scanStatus.phase) {
      case "discovery":
        return { label: "Scanning files", sublabel: "Finding photos in your library" };
      case "exif":
        return { label: "Extracting metadata", sublabel: "Reading EXIF data, dates, GPS" };
      case "geocoding":
        return { label: "Geocoding locations", sublabel: "Converting GPS coordinates to places" };
      case "thumbnails":
        return { label: "Generating thumbnails", sublabel: "Creating preview images" };
      case "motion_photos":
        return { label: "Processing motion photos", sublabel: "Extracting video from live photos" };
      case "hashing":
        return { label: "Computing hashes", sublabel: "Finding duplicate photos" };
      case "clip":
        return { label: "Analyzing images", sublabel: "Tagging photos with AI" };
      case "faces":
        return { label: "Detecting faces", sublabel: "Finding and clustering faces" };
      case "captioning":
        return { label: "Generating captions", sublabel: "Describing photos with AI" };
      case "events":
        return { label: "Detecting events", sublabel: "Grouping photos into events" };
      default:
        return { label: "Processing", sublabel: "" };
    }
  };

  const info = getPhaseInfo();

  return (
    <div className="flex items-center gap-3 text-sm text-gray-600 bg-white/90 backdrop-blur-sm px-4 py-2 rounded-lg shadow-sm border border-gray-200">
      <Loader2 className="w-4 h-4 animate-spin text-primary-500" />
      <div className="flex flex-col">
        <span className="font-medium">{info.label}</span>
        {info.sublabel && <span className="text-xs text-gray-400">{info.sublabel}</span>}
      </div>
      {scanStatus.total_files > 0 && (
        <div className="flex items-center gap-2 ml-2">
          <div className="w-24 h-1.5 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-primary-500 rounded-full transition-all duration-300"
              style={{ width: `${overallProgress}%` }}
            />
          </div>
          <span className="text-xs tabular-nums w-10 text-right">{overallProgress}%</span>
        </div>
      )}
      {scanStatus.phase && scanStatus.phase !== "discovery" && scanStatus.phase_total > 0 && (
        <div className="flex items-center gap-1 ml-2 px-2 py-1 bg-gray-100 rounded">
          <span className="text-xs text-gray-500">Phase:</span>
          <span className="text-xs tabular-nums">{phaseProgress}%</span>
        </div>
      )}
      {scanStatus.current_file && (
        <span className="text-xs text-gray-400 max-w-48 truncate ml-2 hidden sm:inline">
          {scanStatus.current_file.split(/[\\/]/).pop()}
        </span>
      )}
    </div>
  );
}
