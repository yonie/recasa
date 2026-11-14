import { create } from "zustand";
import type { PhotoDetail, PhotoSummary } from "../api/client";

export type GridSize = "S" | "M" | "L";
export type GridFit = "square" | "full";

/**
 * Client-only UI state. Server data (stats, photo lists, pipeline status)
 * lives in react-query, not here.
 */
interface AppStore {
  // Viewer
  viewerPhoto: PhotoDetail | null;
  viewerOpen: boolean;
  viewerPhotoList: PhotoSummary[];
  viewerIndex: number;
  openViewer: (photo: PhotoDetail, photoList?: PhotoSummary[], index?: number) => void;
  closeViewer: () => void;
  setViewerPhoto: (photo: PhotoDetail) => void;
  setViewerIndex: (index: number) => void;

  // Grid size
  gridSize: GridSize;
  setGridSize: (size: GridSize) => void;

  // Grid fit: cropped squares vs full (letterboxed) photos
  gridFit: GridFit;
  setGridFit: (fit: GridFit) => void;

  // Mobile sidebar
  sidebarOpen: boolean;
  closeSidebar: () => void;
  toggleSidebar: () => void;
}

/** A persisted preference, falling back when storage is unavailable or holds junk. */
function loadPref<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = localStorage.getItem(key);
    return allowed.includes(value as T) ? (value as T) : fallback;
  } catch {
    return fallback;
  }
}

function savePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Private browsing or a full quota: the preference just won't persist.
  }
}

export const useStore = create<AppStore>((set) => ({
  // Viewer
  viewerPhoto: null,
  viewerOpen: false,
  viewerPhotoList: [],
  viewerIndex: -1,
  openViewer: (photo, photoList = [], index = -1) =>
    set({ viewerPhoto: photo, viewerOpen: true, viewerPhotoList: photoList, viewerIndex: index }),
  closeViewer: () =>
    set({ viewerPhoto: null, viewerOpen: false, viewerPhotoList: [], viewerIndex: -1 }),
  setViewerPhoto: (photo) => set({ viewerPhoto: photo }),
  setViewerIndex: (index) => set({ viewerIndex: index }),

  gridSize: loadPref<GridSize>("gridSize", ["S", "M", "L"], "M"),
  setGridSize: (size) => {
    savePref("gridSize", size);
    set({ gridSize: size });
  },

  gridFit: loadPref<GridFit>("gridFit", ["square", "full"], "square"),
  setGridFit: (fit) => {
    savePref("gridFit", fit);
    set({ gridFit: fit });
  },

  // Mobile sidebar
  sidebarOpen: false,
  closeSidebar: () => set({ sidebarOpen: false }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
}));
