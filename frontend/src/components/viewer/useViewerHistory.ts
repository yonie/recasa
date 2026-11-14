import { useEffect, useRef } from "react";
import { useStore } from "../../store/useStore";

/**
 * Give the open viewer its own history entry, so the address bar shows a
 * shareable /photos/<hash> and the browser's Back button (or the iOS back
 * swipe) closes the viewer instead of leaving the page underneath.
 *
 * This deliberately bypasses react-router: the page below must not re-render
 * or lose its scroll position while the viewer is up.
 */
export function useViewerHistory(viewerOpen: boolean, closeViewer: () => void) {
  const pushed = useRef(false);
  // The URL we had before opening, restored on close.
  const previousUrl = useRef<string | null>(null);

  useEffect(() => {
    if (viewerOpen) {
      if (!pushed.current) {
        previousUrl.current = window.location.pathname + window.location.search;
        const hash = useStore.getState().viewerPhoto?.file_hash || "";
        window.history.pushState({ viewerOpen: true }, "", `/photos/${hash}`);
        pushed.current = true;
      }

      const handlePopState = () => {
        if (pushed.current) {
          closeViewer();
          pushed.current = false;
        }
      };
      window.addEventListener("popstate", handlePopState);
      return () => window.removeEventListener("popstate", handlePopState);
    }

    // Closed by the UI rather than Back: put the page's URL back in place.
    if (pushed.current && previousUrl.current) {
      window.history.replaceState(null, "", previousUrl.current);
      previousUrl.current = null;
    }
    pushed.current = false;
  }, [viewerOpen, closeViewer]);
}
