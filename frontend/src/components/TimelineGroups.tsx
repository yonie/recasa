import type { ReactNode } from "react";
import { clsx } from "clsx";
import type { TimelineGroup } from "../api/client";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { PhotoGrid } from "./PhotoGrid";

interface TimelineGroupsProps {
  groups: TimelineGroup[];
  /** Heading text for a group key ("2024-03"). */
  label: (date: string) => string;
  /** Muted text after the heading, e.g. "94 photos". */
  count: (group: TimelineGroup) => ReactNode;
  /** Sticky offset and stacking of the group headings: they must sit just
   *  below whatever sticky page header the page has. */
  headingClassName: string;
}

/**
 * Photos in date groups (Photos, Videos, a year), each group a heading and its
 * own grid. The viewer steps through one group at a time. One grid per group
 * is also what lets `content-visibility` skip the off-screen ones.
 */
export function TimelineGroups({ groups, label, count, headingClassName }: TimelineGroupsProps) {
  const openPhoto = useOpenPhoto();
  return (
    <>
      {groups.map((group) => (
        <div key={group.date}>
          <div className={clsx("sticky bg-white/95 px-4 py-2 border-b border-gray-100", headingClassName)}>
            <h2 className="text-sm font-semibold text-gray-700">
              {label(group.date)}
              <span className="ml-2 text-gray-400 font-normal">{count(group)}</span>
            </h2>
          </div>
          <PhotoGrid photos={group.photos} onPhotoClick={openPhoto} showControls={false} />
        </div>
      ))}
    </>
  );
}
