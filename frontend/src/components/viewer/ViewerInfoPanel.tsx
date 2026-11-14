import type { ReactNode } from "react";
import { Camera, Clock, HardDrive, MapPin, MessageSquare, Tag, Users } from "lucide-react";
import type { PhotoDetail } from "../../api/client";
import { formatBytes } from "../../lib/format";
import { getTagColor } from "../../lib/tagColor";

function Section({ title, gap = "gap-1.5", children }: { title: ReactNode; gap?: string; children: ReactNode }) {
  return (
    <section>
      <h3 className={`text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2 flex items-center ${gap}`}>
        {title}
      </h3>
      {children}
    </section>
  );
}

const SHORTCUTS: [string, string][] = [
  ["Esc", "Close"],
  ["F", "Favorite"],
  ["R", "Flag for removal"],
  ["P", "To Print"],
  ["I", "Toggle info"],
  ["← →", "Navigate"],
];

/** File, date, place, camera, caption, tags and people for the photo on screen. */
export function ViewerInfoPanel({ detail }: { detail: PhotoDetail }) {
  const { exif, location } = detail;
  return (
    <div className="w-full sm:w-80 bg-gray-900 text-white overflow-y-auto border-t sm:border-t-0 sm:border-l border-gray-700 fixed sm:relative bottom-0 left-0 right-0 max-h-[50vh] sm:max-h-full">
      <div className="p-4 space-y-6">
        <Section title="File">
          <p className="text-sm font-medium break-all">{detail.file_name}</p>
          <p className="text-xs text-gray-400 mt-1">{detail.file_path}</p>
          {detail.width && detail.height && (
            <p className="text-xs text-gray-400">
              {detail.width} x {detail.height}
            </p>
          )}
          <p className="text-xs text-gray-400">
            <HardDrive className="w-3 h-3 inline mr-1" />
            {formatBytes(detail.file_size)}
          </p>
        </Section>

        {detail.date_taken && (
          <Section title="Date">
            <p className="text-sm flex items-center gap-2">
              <Clock className="w-4 h-4 text-gray-400" />
              {new Date(detail.date_taken).toLocaleString()}
            </p>
          </Section>
        )}

        {location && (
          <Section title="Location">
            <p className="text-sm flex items-center gap-2">
              <MapPin className="w-4 h-4 text-gray-400" />
              {location.address || `${location.city}, ${location.country}`}
            </p>
            {location.latitude && location.longitude && (
              <p className="text-xs text-gray-400 mt-1">
                {location.latitude.toFixed(6)}, {location.longitude.toFixed(6)}
              </p>
            )}
          </Section>
        )}

        {exif && (exif.camera_make || exif.camera_model) && (
          <Section title="Camera">
            <p className="text-sm flex items-center gap-2">
              <Camera className="w-4 h-4 text-gray-400" />
              {[exif.camera_make, exif.camera_model].filter(Boolean).join(" ")}
            </p>
            {exif.lens_model && <p className="text-xs text-gray-400 mt-1">{exif.lens_model}</p>}
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-gray-400">
              {exif.focal_length && <span>{exif.focal_length}mm</span>}
              {exif.aperture && <span>f/{exif.aperture}</span>}
              {exif.shutter_speed && <span>{exif.shutter_speed}s</span>}
              {exif.iso && <span>ISO {exif.iso}</span>}
            </div>
          </Section>
        )}

        {detail.caption && (
          <Section
            title={
              <>
                <MessageSquare className="w-3.5 h-3.5" />
                AI Caption
              </>
            }
          >
            <p className="text-sm text-gray-300 italic">{detail.caption}</p>
          </Section>
        )}

        {detail.tags.length > 0 && (
          <Section
            gap="gap-2"
            title={
              <>
                <Tag className="w-3.5 h-3.5" />
                Tags
              </>
            }
          >
            <div className="flex flex-wrap gap-1.5">
              {detail.tags.map((t) => {
                const color = getTagColor(t.name);
                return (
                  <span
                    key={t.tag_id}
                    className="px-2 py-0.5 rounded-full text-xs"
                    style={{ backgroundColor: color.bg, color: color.text }}
                  >
                    {t.name}
                  </span>
                );
              })}
            </div>
          </Section>
        )}

        {detail.faces.length > 0 && (
          <Section
            title={
              <>
                <Users className="w-3.5 h-3.5" />
                People ({detail.faces.length})
              </>
            }
          >
            <div className="space-y-1">
              {detail.faces.map((face) => (
                <div key={face.face_id} className="text-sm text-gray-300">
                  {face.person_name || `Person ${face.person_id || "?"}`}
                </div>
              ))}
            </div>
          </Section>
        )}

        <Section title="Shortcuts">
          <div className="grid grid-cols-2 gap-1 text-xs text-gray-500">
            {SHORTCUTS.map(([key, action]) => (
              <Shortcut key={key} keyLabel={key} action={action} />
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}

function Shortcut({ keyLabel, action }: { keyLabel: string; action: string }) {
  return (
    <>
      <span className="font-mono bg-gray-800 px-1.5 py-0.5 rounded text-center">{keyLabel}</span>
      <span>{action}</span>
    </>
  );
}
