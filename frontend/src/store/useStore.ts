import { create } from "zustand";
import type { PhotoDetail, PhotoSummary, ScanStatus, LibraryStats } from "../api/client";

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

  // Scan status
  scanStatus: ScanStatus | null;
  setScanStatus: (status: ScanStatus) => void;

  // Stats
  stats: LibraryStats | null;
  setStats: (stats: LibraryStats) => void;

  // Search
  searchQuery: string;
  setSearchQuery: (query: string) => void;
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

  // Scan
  scanStatus: null,
  setScanStatus: (status) => set({ scanStatus: status }),

  // Stats
  stats: null,
  setStats: (stats) => set({ stats }),

  // Search
  searchQuery: "",
  setSearchQuery: (query) => set({ searchQuery: query }),
}));
