import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

/** Outcome of a toggle: the new state, and the refetch that follows it. */
export interface ToggleResult {
  value: boolean;
  /** Settles once every visible list has refetched (e.g. a flagged tile is gone). */
  refreshed: Promise<void>;
}

/**
 * Favorite / flag / print actions with the cache refresh that has to follow
 * them. A toggle changes which lists a photo belongs to, the sidebar counts
 * and the viewer's detail, so the whole cache is invalidated: in a
 * single-user app that is cheap and always correct. Errors propagate; callers
 * decide whether to show them.
 */
export function usePhotoActions() {
  const queryClient = useQueryClient();

  return useMemo(() => {
    const refresh = () => queryClient.invalidateQueries();
    const toggled = (value: boolean): ToggleResult => ({ value, refreshed: refresh() });

    return {
      toggleFavorite: async (hash: string) => toggled((await api.toggleFavorite(hash)).is_favorite),
      togglePrint: async (hash: string) => toggled((await api.togglePrint(hash)).marked_for_print),
      toggleFlag: async (hash: string) => toggled((await api.toggleFlag(hash)).flagged_for_removal),
      clearPrintList: async () => {
        await api.clearPrintList();
        await refresh();
      },
      refresh,
    };
  }, [queryClient]);
}
