import { useCallback, useRef } from "react";
import { useLocation } from "react-router-dom";

/**
 * Saves and restores scroll position for a scrollable container, keyed by
 * route path (sessionStorage) so it survives unmount/remount on navigation.
 *
 * `scrollRef` is a callback ref: it binds the scroll listener the moment the
 * container actually attaches. This matters because pages render a loading
 * spinner first and the real scroll container only appears once data is
 * ready — an ordinary effect would bind against the (absent) spinner node and
 * never re-bind, so nothing ever got saved.
 */
export function useScrollRestore(key: string) {
  const location = useLocation();
  const storageKey = `scroll_${key}_${location.pathname}`;

  const elRef = useRef<HTMLDivElement | null>(null);
  const cleanupRef = useRef<(() => void) | null>(null);

  const scrollRef = useCallback(
    (node: HTMLDivElement | null) => {
      // Detach from a previous node.
      if (cleanupRef.current) {
        cleanupRef.current();
        cleanupRef.current = null;
      }
      elRef.current = node;
      if (!node) return;

      // Track the live position synchronously on every scroll; only the
      // sessionStorage write is throttled (that write is what janks iOS).
      // Never re-read node.scrollTop at teardown — React resets it to 0 as
      // the element detaches, which would clobber the saved position.
      let timeout: number | null = null;
      let last = node.scrollTop;
      const save = () => sessionStorage.setItem(storageKey, String(last));
      const onScroll = () => {
        last = node.scrollTop;
        if (timeout !== null) return;
        timeout = window.setTimeout(() => {
          timeout = null;
          save();
        }, 200);
      };
      node.addEventListener("scroll", onScroll, { passive: true });
      cleanupRef.current = () => {
        node.removeEventListener("scroll", onScroll);
        if (timeout !== null) window.clearTimeout(timeout);
        save();
      };
    },
    [storageKey]
  );

  // Reapply the saved position until the container is tall enough to hold it
  // (images/covers lay out asynchronously, so a single assignment clamps to 0).
  const restoreScroll = useCallback(() => {
    const saved = sessionStorage.getItem(storageKey);
    if (!saved) return;
    const pos = parseInt(saved, 10);
    if (!pos) return;

    const deadline = performance.now() + 1000;
    const apply = () => {
      const el = elRef.current;
      if (!el) {
        if (performance.now() < deadline) requestAnimationFrame(apply);
        return;
      }
      el.scrollTop = pos;
      if (Math.abs(el.scrollTop - pos) > 2 && performance.now() < deadline) {
        requestAnimationFrame(apply);
      }
    };
    requestAnimationFrame(apply);
  }, [storageKey]);

  return { scrollRef, restoreScroll };
}
