import { useCallback } from "react";

import { useStore } from "../store/useStore";
import { api, provisionalDetail, type PhotoSummary } from "../api/client";

/**
 * Open the viewer on a photo without waiting for its detail request.
 *
 * Every grid page used to `await api.getPhoto()` before opening, so a click did
 * nothing at all for the length of a round-trip. The list entry already has
 * what the viewer needs to draw the photo, so open on that and let EXIF, faces
 * and tags fill in when they land.
 */
export function useOpenPhoto() {
  const openViewer = useStore((s) => s.openViewer);
  const setViewerPhoto = useStore((s) => s.setViewerPhoto);

  return useCallback(
    (photo: PhotoSummary, index: number, list: PhotoSummary[] = []) => {
      openViewer(provisionalDetail(photo), list, index);
      api
        .getPhoto(photo.file_hash)
        .then((full) => {
          // Drop a response the user has already navigated away from.
          const s = useStore.getState();
          if (s.viewerOpen && s.viewerPhoto?.file_hash === full.file_hash) {
            setViewerPhoto(full);
          }
        })
        .catch(() => {});
    },
    [openViewer, setViewerPhoto]
  );
}
