import {
  Calendar,
  FileImage,
  FolderOpen,
  Hash,
  Image,
  MapPin,
  Play,
  Sparkles,
  User,
  type LucideIcon,
} from "lucide-react";
import type { StageName } from "../../api/client";

export const STAGE_LABELS: Record<StageName, string> = {
  discovery: "File Discovery",
  exif: "EXIF Extraction",
  geocoding: "Geocoding",
  thumbnails: "Thumbnails",
  motion_photos: "Motion Photos",
  hashing: "Perceptual Hashing",
  faces: "Face Detection",
  captioning: "AI Captioning",
  events: "Event Detection",
};

/** Label for a stage name from the API, which may be one we don't know. */
export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage as StageName] ?? stage;
}

export const STAGE_ICONS: Record<StageName, LucideIcon> = {
  discovery: FolderOpen,
  exif: FileImage,
  geocoding: MapPin,
  thumbnails: Image,
  motion_photos: Play,
  hashing: Hash,
  faces: User,
  captioning: Sparkles,
  events: Calendar,
};

// Stages that can be wiped and rebuilt from the danger zone
export const REBUILDABLE: { stage: StageName; label: string; warning: string }[] = [
  { stage: "geocoding", label: "Rebuild geocoding", warning: "location names" },
  { stage: "hashing", label: "Rebuild hashes & duplicates", warning: "duplicate detection data" },
  { stage: "faces", label: "Rebuild faces", warning: "all detected faces and named people" },
  { stage: "captioning", label: "Rebuild captions", warning: "all AI captions" },
  { stage: "events", label: "Rebuild events", warning: "all detected events" },
];
