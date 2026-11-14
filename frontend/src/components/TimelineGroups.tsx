import { useEffect, useRef, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import type { TimelineGroup } from "../api/client";
import { useOpenPhoto } from "../hooks/useOpenPhoto";
import { estimateGridHeight } from "../lib/gridLayout";
import { useStore } from "../store/useStore";
import { PhotoGrid, type OpenPhoto } from "./PhotoGrid";

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

// Groups rendered straight away; the rest wait until they come near the
// viewport. Two months fill the first screen even in the large grid.
const EAGER_GROUPS = 2;
// How far ahead of the visible area a group starts rendering, so it is
// ready before it scrolls into view.
const RENDER_AHEAD = "2000px 0px";
// Tiles added per frame while a group renders. A month can hold 300+ photos,
// and mounting them in one go is a long task that drops frames mid-scroll on
// a phone; in slices each frame stays short.
const TILES_PER_FRAME = 48;

/**
 * Photos in date groups (Photos, Videos, a year), each group a heading and its
 * own grid. The viewer steps through one group at a time. One grid per group
 * is also what lets `content-visibility` skip the off-screen ones.
 */
export function TimelineGroups({ groups, label, count, headingClassName }: TimelineGroupsProps) {
  const openPhoto = useOpenPhoto();
  const idleMounted = useIdleCounter(groups.length);
  return (
    <>
      {groups.map((group, i) => (
        <div key={group.date}>
          <div className={clsx("sticky bg-white/95 px-4 py-2 border-b border-gray-100", headingClassName)}>
            <h2 className="text-sm font-semibold text-gray-700">
              {label(group.date)}
              <span className="ml-2 text-gray-400 font-normal">{count(group)}</span>
            </h2>
          </div>
          <LazyGroupGrid
            group={group}
            eager={i < EAGER_GROUPS}
            mountNow={i < idleMounted}
            onPhotoClick={openPhoto}
          />
        </div>
      ))}
    </>
  );
}

/**
 * Counts up to `max`, one step per idle period. Groups below the count mount
 * in the background, so by the time anyone scrolls most of the timeline is
 * already rendered and scrolling doesn't have to pay for it.
 */
function useIdleCounter(max: number): number {
  const [count, setCount] = useState(EAGER_GROUPS);
  useEffect(() => {
    if (count >= max) return;
    const next = () => setCount((c) => c + 1);
    if ("requestIdleCallback" in window) {
      const id = window.requestIdleCallback(next, { timeout: 2000 });
      return () => window.cancelIdleCallback(id);
    }
    const t = setTimeout(next, 100);
    return () => clearTimeout(t);
  }, [count, max]);
  return count;
}

/** The nearest scrolling ancestor, which is what "near the viewport" means here. */
function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p; p = p.parentElement) {
    const { overflowY } = getComputedStyle(p);
    if (overflowY === "auto" || overflowY === "scroll") return p;
  }
  return null;
}

/**
 * A group's grid, mounted the first time it nears the viewport and kept
 * afterwards. The Photos timeline holds some 2,400 photos; mounting every
 * tile up front cost hundreds of milliseconds on each visit, most of it for
 * months nobody scrolls to. Until then a placeholder of the grid's estimated
 * height keeps the scrollbar and the positions below it honest.
 */
function LazyGroupGrid({
  group,
  eager,
  mountNow,
  onPhotoClick,
}: {
  group: TimelineGroup;
  eager: boolean;
  /** Mount even though it isn't near the viewport (background rendering). */
  mountNow: boolean;
  onPhotoClick: OpenPhoto;
}) {
  const gridSize = useStore((s) => s.gridSize);
  const [mounted, setMounted] = useState(eager);
  if (mountNow && !mounted) setMounted(true);
  const total = group.photos.length;
  const [shown, setShown] = useState(eager ? total : 0);
  const placeholder = useRef<HTMLDivElement>(null);

  // Once mounted, grow the rendered tiles a slice per frame up to the whole group.
  useEffect(() => {
    if (!mounted || shown >= total) return;
    const id = requestAnimationFrame(() => setShown((n) => Math.min(total, n + TILES_PER_FRAME)));
    return () => cancelAnimationFrame(id);
  }, [mounted, shown, total]);

  useEffect(() => {
    const el = placeholder.current;
    if (mounted || !el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setMounted(true);
      },
      { root: scrollParent(el), rootMargin: RENDER_AHEAD }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [mounted]);

  if (!mounted) {
    return <div ref={placeholder} style={{ height: estimateGridHeight(gridSize, total) }} />;
  }
  const complete = shown >= total;
  return (
    // While slices are still arriving, hold the final height so nothing below jumps.
    <div style={complete ? undefined : { minHeight: estimateGridHeight(gridSize, total) }}>
      <PhotoGrid
        photos={group.photos}
        renderCount={complete ? undefined : shown}
        onPhotoClick={onPhotoClick}
        showControls={false}
      />
    </div>
  );
}
