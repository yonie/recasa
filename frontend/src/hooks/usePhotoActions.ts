import { useMemo } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, type PhotoSummary } from "../api/client";
import { queryKeys } from "../api/queryKeys";

/** Outcome of a toggle: the new state, and the refetch that follows it. */
export interface ToggleResult {
  value: boolean;
  /** Settles once the lists the toggle affects have refetched (e.g. a flagged tile is gone). */
  refreshed: Promise<void>;
}

type PhotoPatch = Partial<Pick<PhotoSummary, "is_favorite" | "marked_for_print">>;

/**
 * `value` with every photo object for `hash` updated by `patch`. Untouched
 * branches keep their identity, so memoized tiles for other photos don't
 * re-render, and a result identical to the input means "not in here".
 */
function patchPhotos(value: unknown, hash: string, patch: PhotoPatch): unknown {
  if (Array.isArray(value)) {
    let changed = false;
    const out = value.map((item) => {
      const next = patchPhotos(item, hash, patch);
      if (next !== item) changed = true;
      return next;
    });
    return changed ? out : value;
  }
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if (obj.file_hash === hash) {
      const differs = (Object.keys(patch) as (keyof PhotoPatch)[]).some(
        (k) => k in obj && obj[k] !== patch[k]
      );
      return differs ? { ...obj, ...patch } : value;
    }
    let changed = false;
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
      const next = patchPhotos(v, hash, patch);
      if (next !== v) changed = true;
      out[k] = next;
    }
    return changed ? out : value;
  }
  return value;
}

/**
 * Write a favorite/print change into every cached list and detail that holds
 * the photo. Keeps each query's own fetch time, so this doesn't postpone a
 * refetch that was due anyway.
 */
function patchCachedPhoto(queryClient: QueryClient, hash: string, patch: PhotoPatch) {
  for (const query of queryClient.getQueryCache().findAll()) {
    const data = query.state.data;
    if (data === undefined) continue;
    const next = patchPhotos(data, hash, patch);
    if (next !== data) {
      queryClient.setQueryData(query.queryKey, next, { updatedAt: query.state.dataUpdatedAt });
    }
  }
}

/**
 * Favorite / flag / print actions with the cache updates that have to follow
 * them. Errors propagate; callers decide whether to show them.
 *
 * A favorite or print mark only changes membership of one list (Favorites,
 * To Print) and the sidebar counts, so those are refetched and every other
 * cached copy of the photo is patched in place. Refetching everything instead
 * meant re-reading the whole Photos timeline (over a megabyte, seconds of Pi
 * CPU) for every star clicked there. A flag hides the photo from every view,
 * so that one still refetches all active lists.
 */
export function usePhotoActions() {
  const queryClient = useQueryClient();

  return useMemo(() => {
    const refreshAll = () => queryClient.invalidateQueries();

    const markToggled = async (
      hash: string,
      patch: PhotoPatch,
      list: Record<string, unknown>
    ): Promise<void> => {
      patchCachedPhoto(queryClient, hash, patch);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.photoList(list) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.stats }),
      ]);
    };

    return {
      toggleFavorite: async (hash: string): Promise<ToggleResult> => {
        const value = (await api.toggleFavorite(hash)).is_favorite;
        return { value, refreshed: markToggled(hash, { is_favorite: value }, { favorite: true }) };
      },
      togglePrint: async (hash: string): Promise<ToggleResult> => {
        const value = (await api.togglePrint(hash)).marked_for_print;
        return {
          value,
          refreshed: markToggled(hash, { marked_for_print: value }, { marked_for_print: true }),
        };
      },
      toggleFlag: async (hash: string): Promise<ToggleResult> => {
        const value = (await api.toggleFlag(hash)).flagged_for_removal;
        return { value, refreshed: refreshAll() };
      },
      clearPrintList: async () => {
        await api.clearPrintList();
        await refreshAll();
      },
    };
  }, [queryClient]);
}
