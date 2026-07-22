import { useEffect, useRef, useCallback } from "react";
import { useLocation } from "react-router-dom";

/**
 * Saves and restores scroll position for a scrollable container.
 * Uses sessionStorage keyed by the route path so position survives
 * component unmount/remount during navigation.
 */
export function useScrollRestore(key: string) {
  const location = useLocation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const storageKey = `scroll_${key}_${location.pathname}`;

  // Restore scroll position after content loads
  const restoreScroll = useCallback(() => {
    const saved = sessionStorage.getItem(storageKey);
    if (saved && scrollRef.current) {
      const pos = parseInt(saved, 10);
      // Use requestAnimationFrame to wait for render
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = pos;
        }
      });
    }
  }, [storageKey]);

  // Save scroll position, throttled — a synchronous sessionStorage write on
  // every scroll event janks scrolling on iOS. Flush on unmount so the final
  // position is captured when navigating away.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    let timeout: number | null = null;
    const save = () => sessionStorage.setItem(storageKey, String(el.scrollTop));

    const handleScroll = () => {
      if (timeout !== null) return;
      timeout = window.setTimeout(() => {
        timeout = null;
        save();
      }, 250);
    };

    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", handleScroll);
      if (timeout !== null) window.clearTimeout(timeout);
      save();
    };
  }, [storageKey]);

  return { scrollRef, restoreScroll };
}
