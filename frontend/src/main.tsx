import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { queryKeys } from "./api/queryKeys";
import { persistQuery, restoreQuery } from "./lib/persistQuery";
import "./index.css";

// Single caching layer for all JSON data: pages render instantly from cache
// on revisit and revalidate in the background. The API sends no HTTP cache
// headers on JSON: freshness is owned here, not split across two layers.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 30 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function render() {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </React.StrictMode>
  );
}

// The Photos timeline is the landing page and the slowest request; show the
// last copy while the fresh one loads. Opening on Photos waits (briefly) for
// the saved copy; any other page renders at once and restores alongside.
const restored = restoreQuery(queryClient, queryKeys.homeTimeline);
persistQuery(queryClient, queryKeys.homeTimeline);
if (window.location.pathname === "/") {
  void restored.then(render);
} else {
  render();
}
