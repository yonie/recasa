import { lazy, Suspense, useCallback } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
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
import { plural } from "../lib/format";

// Leaflet is the largest dependency and only this page needs it.
const MapView = lazy(() => import("./map/MapView").then((m) => ({ default: m.MapView })));

// Location lists follow geocoding as it runs, so they poll.
const LOCATION_POLL_MS = 10_000;

/** Route segments arrive percent-encoded; titles and API calls want plain text. */
const decoded = (segment: string | undefined) => (segment ? decodeURIComponent(segment) : "");

function locationPath(country: string, city?: string | null) {
  return `/locations/${encodeURIComponent(country)}${city ? `/${encodeURIComponent(city)}` : ""}`;
}

// Location city photos view (route: /locations/:country/:city)
export function LocationCityPhotos() {
  const params = useParams<{ country: string; city: string }>();
  const navigate = useNavigate();
  const country = decoded(params.country);
  const city = decoded(params.city);

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.locationPhotos(params.country, params.city),
    queryFn: () => api.getLocationPhotos({ page_size: 200, country, city }),
    enabled: !!country && !!city,
    refetchInterval: LOCATION_POLL_MS,
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
  const params = useParams<{ country: string }>();
  const navigate = useNavigate();
  const country = decoded(params.country);

  const { data: cities = [], isLoading, error } = useQuery({
    queryKey: queryKeys.cities(params.country),
    queryFn: () => api.getCities(country),
    enabled: !!country,
    refetchInterval: LOCATION_POLL_MS,
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
  const [searchParams, setSearchParams] = useSearchParams();
  const viewMode: ViewMode = (searchParams.get("view") || "map") === "map" ? "map" : "countries";
  const navigate = useNavigate();

  const countriesQuery = useQuery({
    queryKey: queryKeys.countries,
    queryFn: api.getCountries,
    refetchInterval: LOCATION_POLL_MS,
  });
  const mapQuery = useQuery({
    queryKey: queryKeys.mapPoints,
    queryFn: api.getMapPoints,
    refetchInterval: LOCATION_POLL_MS,
  });
  const countries = countriesQuery.data ?? [];
  const mapPoints = mapQuery.data ?? [];

  const setViewMode = (mode: ViewMode) => setSearchParams({ view: mode });

  // Stable, so the map's memoized markers survive this page's 10s polling.
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
