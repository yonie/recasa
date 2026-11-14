import { lazy, Suspense, useEffect, type ComponentType } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import { Sidebar } from "./components/Sidebar";
import { SearchBar } from "./components/SearchBar";
import { PageSpinner } from "./components/Page";
import { PhotoViewer } from "./components/viewer/PhotoViewer";

// Eager: the landing page and the deep-link route. Every other page is its own
// chunk, so the first load parses only what the Photos page needs; the rest
// are fetched while the browser is idle right after, and are ready (and
// cached) before anyone clicks.
import { Home } from "./pages/Home";
import { PhotoPage } from "./pages/PhotoPage";

const pageLoaders = {
  folders: () => import("./pages/Folders"),
  years: () => import("./pages/Years"),
  favorites: () => import("./pages/Favorites"),
  toPrint: () => import("./pages/ToPrint"),
  flagged: () => import("./pages/Flagged"),
  videos: () => import("./pages/Videos"),
  duplicates: () => import("./pages/Duplicates"),
  largeFiles: () => import("./pages/LargeFiles"),
  search: () => import("./pages/SearchResults"),
  people: () => import("./pages/people"),
  events: () => import("./pages/Events"),
  locations: () => import("./pages/Locations"),
  pipeline: () => import("./pages/pipeline"),
  tags: () => import("./pages/Tags"),
  exportImport: () => import("./pages/ExportImport"),
};

/** A lazily loaded named export. */
function page<M>(load: () => Promise<M>, pick: (m: M) => ComponentType) {
  return lazy(() => load().then((m) => ({ default: pick(m) })));
}

const Folders = page(pageLoaders.folders, (m) => m.Folders);
const Years = page(pageLoaders.years, (m) => m.Years);
const Favorites = page(pageLoaders.favorites, (m) => m.Favorites);
const ToPrint = page(pageLoaders.toPrint, (m) => m.ToPrint);
const Flagged = page(pageLoaders.flagged, (m) => m.Flagged);
const Videos = page(pageLoaders.videos, (m) => m.Videos);
const Duplicates = page(pageLoaders.duplicates, (m) => m.Duplicates);
const LargeFiles = page(pageLoaders.largeFiles, (m) => m.LargeFiles);
const SearchResults = page(pageLoaders.search, (m) => m.SearchResults);
const People = page(pageLoaders.people, (m) => m.People);
const PersonDetail = page(pageLoaders.people, (m) => m.PersonDetail);
const TogetherDetail = page(pageLoaders.people, (m) => m.TogetherDetail);
const Events = page(pageLoaders.events, (m) => m.Events);
const EventDetail = page(pageLoaders.events, (m) => m.EventDetail);
const Locations = page(pageLoaders.locations, (m) => m.Locations);
const LocationCountryCities = page(pageLoaders.locations, (m) => m.LocationCountryCities);
const LocationCityPhotos = page(pageLoaders.locations, (m) => m.LocationCityPhotos);
const Pipeline = page(pageLoaders.pipeline, (m) => m.Pipeline);
const Tags = page(pageLoaders.tags, (m) => m.Tags);
const TagDetail = page(pageLoaders.tags, (m) => m.TagDetail);
const ExportImport = page(pageLoaders.exportImport, (m) => m.ExportImport);

/** Fetch every page chunk once the browser has nothing better to do. */
function usePreloadPages() {
  useEffect(() => {
    const preload = () => Object.values(pageLoaders).forEach((load) => void load().catch(() => {}));
    if ("requestIdleCallback" in window) {
      const id = window.requestIdleCallback(preload, { timeout: 3000 });
      return () => window.cancelIdleCallback(id);
    }
    const t = setTimeout(preload, 1500);
    return () => clearTimeout(t);
  }, []);
}

function AppContent() {
  usePreloadPages();
  return (
    <div className="flex h-screen h-[100dvh]">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <SearchBar />
        <main className="flex-1 overflow-hidden">
          <Suspense fallback={<PageSpinner />}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/folders" element={<Folders />} />
              <Route path="/folders/*" element={<Folders />} />
              <Route path="/years" element={<Years />} />
              <Route path="/years/:year" element={<Years />} />
              <Route path="/favorites" element={<Favorites />} />
              <Route path="/to-print" element={<ToPrint />} />
              <Route path="/flagged" element={<Flagged />} />
              <Route path="/videos" element={<Videos />} />
              <Route path="/people" element={<People />} />
              <Route path="/people/together/:personIds" element={<TogetherDetail />} />
              <Route path="/people/:personId" element={<PersonDetail />} />
              <Route path="/events" element={<Events />} />
              <Route path="/events/:eventId" element={<EventDetail />} />
              <Route path="/locations" element={<Locations />} />
              <Route path="/locations/:country" element={<LocationCountryCities />} />
              <Route path="/locations/:country/:city" element={<LocationCityPhotos />} />
              <Route path="/tags" element={<Tags />} />
              <Route path="/tags/:tagId" element={<TagDetail />} />
              <Route path="/duplicates" element={<Duplicates />} />
              <Route path="/large-files" element={<LargeFiles />} />
              <Route path="/export-import" element={<ExportImport />} />
              <Route path="/search" element={<SearchResults />} />
              <Route path="/pipeline" element={<Pipeline />} />
              <Route path="/photos/:hash" element={<PhotoPage />} />
            </Routes>
          </Suspense>
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
