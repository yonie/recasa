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

  // Save scroll position on scroll
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const handleScroll = () => {
      sessionStorage.setItem(storageKey, String(el.scrollTop));
    };

    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, [storageKey]);

  return { scrollRef, restoreScroll };
}
