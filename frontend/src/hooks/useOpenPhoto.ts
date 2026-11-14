import { useCallback } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { useStore } from "../store/useStore";
import { api, provisionalDetail, type PhotoDetail, type PhotoSummary } from "../api/client";
import { queryKeys } from "../api/queryKeys";

/**
 * A photo's full detail through the query cache, so stepping back to a photo,
 * or onto one the viewer prefetched, needs no request at all.
 */
export function fetchPhotoDetail(queryClient: QueryClient, hash: string): Promise<PhotoDetail> {
  return queryClient.fetchQuery({ queryKey: queryKeys.photo(hash), queryFn: () => api.getPhoto(hash) });
}

/** The cached detail if there is one, else a stand-in built from the list entry. */
export function bestDetail(queryClient: QueryClient, photo: PhotoSummary): PhotoDetail {
  return queryClient.getQueryData<PhotoDetail>(queryKeys.photo(photo.file_hash)) ?? provisionalDetail(photo);
}

/**
 * Open the viewer on a photo without waiting for its detail request.
 *
 * Every grid page used to `await api.getPhoto()` before opening, so a click did
 * nothing at all for the length of a round-trip. The list entry already has
 * what the viewer needs to draw the photo, so open on that and let EXIF, faces
 * and tags fill in when they land.
 */
export function useOpenPhoto() {
  const queryClient = useQueryClient();
  const openViewer = useStore((s) => s.openViewer);
  const setViewerPhoto = useStore((s) => s.setViewerPhoto);

  return useCallback(
    (photo: PhotoSummary, index: number, list: PhotoSummary[] = []) => {
      openViewer(bestDetail(queryClient, photo), list, index);
      fetchPhotoDetail(queryClient, photo.file_hash)
        .then((full) => {
          // Drop a response the user has already navigated away from.
          const s = useStore.getState();
          if (s.viewerOpen && s.viewerPhoto?.file_hash === full.file_hash) {
            setViewerPhoto(full);
          }
        })
        .catch(() => {});
    },
    [queryClient, openViewer, setViewerPhoto]
  );
}

/**
 * Open the viewer on a single photo known only by hash (map popups). There
 * is no list entry to draw from, so this waits for the detail.
 */
export function useOpenPhotoByHash() {
  const queryClient = useQueryClient();
  const openViewer = useStore((s) => s.openViewer);
  return useCallback(
    (hash: string) => {
      fetchPhotoDetail(queryClient, hash)
        .then((detail) => openViewer(detail))
        .catch(() => {});
    },
    [queryClient, openViewer]
  );
}
