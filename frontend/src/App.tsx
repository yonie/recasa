import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import { Sidebar } from "./components/Sidebar";
import { SearchBar } from "./components/SearchBar";
import { PhotoViewer } from "./components/PhotoViewer";

import { Home } from "./pages/Home";
import { Folders } from "./pages/Folders";
import { Years } from "./pages/Years";
import { Favorites } from "./pages/Favorites";
import { Duplicates } from "./pages/Duplicates";
import { LargeFiles } from "./pages/LargeFiles";
import { SearchResults } from "./pages/SearchResults";
import { People } from "./pages/People";
import { Events } from "./pages/Events";
import { Locations } from "./pages/Locations";
import { Pipeline } from "./pages/Pipeline";
import { Tags } from "./pages/Tags";

import { useScanStatus } from "./hooks/useScanStatus";
import { useStore } from "./store/useStore";
import { api } from "./api/client";

function AppContent() {
  const setStats = useStore((s) => s.setStats);

  // Connect to scan WebSocket
  useScanStatus();

  // Load library stats
  useEffect(() => {
    async function loadStats() {
      try {
        const stats = await api.getStats();
        setStats(stats);
      } catch {
        // API might not be ready yet
      }
    }

    loadStats();
    // Refresh stats every 30 seconds
    const interval = setInterval(loadStats, 30000);
    return () => clearInterval(interval);
  }, [setStats]);

  return (
    <div className="flex h-screen">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <SearchBar />
        <main className="flex-1 overflow-hidden">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/folders" element={<Folders />} />
            <Route path="/years" element={<Years />} />
            <Route path="/favorites" element={<Favorites />} />
            <Route path="/people" element={<People />} />
            <Route path="/events" element={<Events />} />
            <Route path="/locations" element={<Locations />} />
            <Route path="/tags" element={<Tags />} />
            <Route path="/duplicates" element={<Duplicates />} />
            <Route path="/large-files" element={<LargeFiles />} />
            <Route path="/search" element={<SearchResults />} />
            <Route path="/pipeline" element={<Pipeline />} />
          </Routes>
        </main>
      </div>

      {/* Global photo viewer overlay */}
      <PhotoViewer />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}
