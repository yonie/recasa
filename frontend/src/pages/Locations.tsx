import { lazy, Suspense, useCallback, useEffect, useRef } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, List, Map, MapPin } from "lucide-react";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  BackButton,
  EmptyState,
  ErrorState,
  PageHeader,
  PageSpinner,
  PageTitle,
  PhotoListLayout,
} from "../components/Page";
import { usePipelineStatus } from "../hooks/useServerState";
import { plural } from "../lib/format";

// Leaflet is the largest dependency and only this page needs it.
const MapView = lazy(() => import("./map/MapView").then((m) => ({ default: m.MapView })));

// While geocoding runs, location lists poll so new places appear as they
// are resolved.
const LOCATION_POLL_MS = 10_000;

/**
 * Poll interval for location queries: every 10 s while the geocoding queue
 * has work, otherwise none (the map-points list alone is ~900 points, and the
 * page used to re-request it every 10 s for as long as it was open). When
 * geocoding finishes, one last refresh picks up its final results. The
 * pipeline status this reads is the sidebar's poll, so it costs nothing extra.
 */
function useLocationPolling(): number | false {
  const status = usePipelineStatus();
  const queue = status?.queues?.geocoding;
  const active = !!queue && queue.pending + queue.processing > 0;
  const queryClient = useQueryClient();
  const wasActive = useRef(active);

  useEffect(() => {
    if (wasActive.current && !active) {
      for (const queryKey of [
        queryKeys.countries,
        queryKeys.mapPoints,
        queryKeys.citiesAll,
        queryKeys.locationPhotosAll,
      ]) {
        void queryClient.invalidateQueries({ queryKey });
      }
    }
    wasActive.current = active;
  }, [active, queryClient]);

  return active ? LOCATION_POLL_MS : false;
}

/** Route segments arrive percent-encoded; titles and API calls want plain text. */
const decoded = (segment: string | undefined) => (segment ? decodeURIComponent(segment) : "");

function locationPath(country: string, city?: string | null) {
  return `/locations/${encodeURIComponent(country)}${city ? `/${encodeURIComponent(city)}` : ""}`;
}

// Location city photos view (route: /locations/:country/:city)
export function LocationCityPhotos() {
  const poll = useLocationPolling();
  const params = useParams<{ country: string; city: string }>();
  const navigate = useNavigate();
  const country = decoded(params.country);
  const city = decoded(params.city);

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.locationPhotos(params.country, params.city),
    queryFn: () => api.getLocationPhotos({ page_size: 200, country, city }),
    enabled: !!country && !!city,
    refetchInterval: poll,
  });

  if (isLoading) return <PageSpinner />;
  if (error && !data) return <ErrorState error={error} />;

  const total = data?.total ?? 0;
  return (
    <PhotoListLayout
      photos={data?.items ?? []}
      header={
        <PageHeader className="flex items-center gap-3">
          <BackButton onClick={() => navigate(-1)} />
          <MapPin className="w-5 h-5 text-gray-400" />
          <PageTitle count={`${total} ${plural(total, "photo")}`}>
            {city}
            {country ? `, ${country}` : ""}
          </PageTitle>
        </PageHeader>
      }
    />
  );
}

// Location country cities view (route: /locations/:country)
export function LocationCountryCities() {
  const poll = useLocationPolling();
  const params = useParams<{ country: string }>();
  const navigate = useNavigate();
  const country = decoded(params.country);

  const { data: cities = [], isLoading, error } = useQuery({
    queryKey: queryKeys.cities(params.country),
    queryFn: () => api.getCities(country),
    enabled: !!country,
    refetchInterval: poll,
  });

  if (isLoading) return <PageSpinner />;
  if (error && !cities.length) return <ErrorState error={error} />;

  return (
    <div className="overflow-y-auto h-full">
      <PageHeader className="flex items-center gap-3">
        <BackButton onClick={() => navigate(-1)} />
        <Globe className="w-5 h-5 text-gray-400" />
        <PageTitle count={`${cities.length} ${plural(cities.length, "city", "cities")}`}>{country}</PageTitle>
      </PageHeader>

      <div className="divide-y divide-gray-50">
        {cities.map((city) => (
          <LocationRow
            key={`${city.city}-${city.country}`}
            icon={MapPin}
            label={city.city}
            count={city.count}
            onClick={() => navigate(locationPath(country, city.city))}
          />
        ))}
      </div>
    </div>
  );
}

function LocationRow({
  icon: Icon,
  label,
  count,
  onClick,
}: {
  icon: typeof Globe;
  label: string;
  count: number;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
    >
      <div className="flex items-center gap-3">
        <Icon className="w-4 h-4 text-gray-400" />
        <span className="text-sm font-medium">{label}</span>
      </div>
      <span className="text-sm text-gray-400">
        {count} {plural(count, "photo")}
      </span>
    </button>
  );
}

type ViewMode = "map" | "countries";

/** List/map switch. The active side is highlighted and does nothing when clicked. */
function ViewToggle({ mode, onChange }: { mode: ViewMode; onChange: (mode: ViewMode) => void }) {
  const button = (target: ViewMode, title: string, Icon: typeof Map) => {
    const active = mode === target;
    return (
      <button
        onClick={active ? undefined : () => onChange(target)}
        className={active ? "p-2 rounded-lg bg-gray-100 transition-colors" : "p-2 rounded-lg hover:bg-gray-100 transition-colors"}
        title={title}
      >
        <Icon className={active ? "w-5 h-5" : "w-5 h-5 text-gray-400"} />
      </button>
    );
  };
  return (
    <div className="flex gap-1">
      {button("countries", "List view", List)}
      {button("map", "Map view", Map)}
    </div>
  );
}

// Locations main view with map/countries toggle (route: /locations)
export function Locations() {
  const poll = useLocationPolling();
  const [searchParams, setSearchParams] = useSearchParams();
  const viewMode: ViewMode = (searchParams.get("view") || "map") === "map" ? "map" : "countries";
  const navigate = useNavigate();

  const countriesQuery = useQuery({
    queryKey: queryKeys.countries,
    queryFn: api.getCountries,
    refetchInterval: poll,
  });
  const mapQuery = useQuery({
    queryKey: queryKeys.mapPoints,
    queryFn: api.getMapPoints,
    refetchInterval: poll,
  });
  const countries = countriesQuery.data ?? [];
  const mapPoints = mapQuery.data ?? [];

  const setViewMode = (mode: ViewMode) => setSearchParams({ view: mode });

  // Stable, so the map's memoized markers survive this page's re-renders.
  const handleLocationClick = useCallback(
    (city: string | null, country: string | null) => {
      if (country) navigate(locationPath(country, city));
    },
    [navigate]
  );

  if (countriesQuery.isLoading || mapQuery.isLoading) return <PageSpinner />;

  if (viewMode === "map") {
    if (mapQuery.error && !mapQuery.data) return <ErrorState error={mapQuery.error} />;
    return (
      <div className="h-full flex flex-col">
        <PageHeader className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Map className="w-5 h-5 text-gray-400" />
            <h1 className="text-lg font-semibold">Map</h1>
          </div>
          <ViewToggle mode="map" onChange={setViewMode} />
        </PageHeader>
        {mapPoints.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-gray-400 gap-2">
            <Map className="w-12 h-12 text-gray-300" />
            <p className="text-lg">No geotagged photos</p>
            <p className="text-sm">Photos with GPS data will appear on the map</p>
          </div>
        ) : (
          <div className="flex-1">
            <Suspense fallback={<PageSpinner />}>
              <MapView points={mapPoints} onLocationClick={handleLocationClick} />
            </Suspense>
          </div>
        )}
      </div>
    );
  }

  if (countriesQuery.error && !countriesQuery.data) return <ErrorState error={countriesQuery.error} />;
  if (countries.length === 0) {
    return (
      <EmptyState
        icon={Globe}
        title="No locations found"
        hint="Photos with GPS data will be grouped by location"
      />
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <PageHeader className="flex items-center justify-between">
        <PageTitle count={`${countries.length} ${plural(countries.length, "country", "countries")}`}>
          Locations
        </PageTitle>
        {mapPoints.length > 0 && <ViewToggle mode="countries" onChange={setViewMode} />}
      </PageHeader>

      <div className="divide-y divide-gray-50">
        {countries.map((country) => (
          <LocationRow
            key={country.country}
            icon={Globe}
            label={country.country}
            count={country.count}
            onClick={() => navigate(locationPath(country.country))}
          />
        ))}
      </div>
    </div>
  );
}
