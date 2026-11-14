import { clsx } from "clsx";
import type { PersonSummary } from "../../api/client";

/** Overlapping round face thumbnails for a group of people. */
export function FaceStack({
  persons,
  size = "w-8 h-8",
  overlap = "-space-x-2",
  ring = "ring-2",
}: {
  persons: PersonSummary[];
  size?: string;
  overlap?: string;
  ring?: string;
}) {
  return (
    <div className={clsx("flex", overlap)}>
      {persons.map(
        (p) =>
          p.face_thumbnail_url && (
            <img
              key={p.person_id}
              src={p.face_thumbnail_url}
              alt=""
              loading="lazy"
              className={clsx(size, "rounded-full object-cover ring-white", ring)}
            />
          )
      )}
    </div>
  );
}
