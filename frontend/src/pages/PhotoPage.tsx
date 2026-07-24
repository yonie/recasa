import { useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useStore } from "../store/useStore";
import { Loader2 } from "lucide-react";

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
    queryKey: ["photo", hash],
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

  return (
    <div className="flex items-center justify-center h-64">
      <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
    </div>
  );
}
