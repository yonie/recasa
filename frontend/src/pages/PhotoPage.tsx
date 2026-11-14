import { useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { PageSpinner } from "../components/Page";
import { useStore } from "../store/useStore";

/**
 * Direct photo link page (route: /photos/:hash)
 * Opens the photo viewer immediately and navigates back to home on close.
 */
export function PhotoPage() {
  const { hash } = useParams<{ hash: string }>();
  const navigate = useNavigate();
  const openViewer = useStore((s) => s.openViewer);
  const viewerOpen = useStore((s) => s.viewerOpen);

  const { data: detail, isError } = useQuery({
    queryKey: queryKeys.photo(hash),
    queryFn: () => api.getPhoto(hash!),
    enabled: !!hash,
    retry: false,
  });

  useEffect(() => {
    if (detail) {
      openViewer(detail);
    }
  }, [detail, openViewer]);

  useEffect(() => {
    if (isError) {
      // Photo not found, go home
      navigate("/", { replace: true });
    }
  }, [isError, navigate]);

  // When viewer is closed, navigate back
  useEffect(() => {
    if (!viewerOpen && hash) {
      // Small delay to avoid navigating before viewer has had a chance to open
      const timeout = setTimeout(() => {
        const viewerIsOpen = useStore.getState().viewerOpen;
        if (!viewerIsOpen) {
          navigate(-1);
        }
      }, 500);
      return () => clearTimeout(timeout);
    }
  }, [viewerOpen, hash, navigate]);

  return <PageSpinner />;
}
