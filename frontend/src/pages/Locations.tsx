import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import { api, type CountryCount, type CityCount, type PhotoSummary, type MapPoint, thumbnailUrl } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { Loader2, MapPin, ArrowLeft, Globe, Map, List } from "lucide-react";
import "leaflet/dist/leaflet.css";

// Fix default marker icon issue with bundlers
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png",
  iconUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
});

function createClusterIcon(count: number): L.DivIcon {
  const size = count > 100 ? 50 : count > 10 ? 40 : 30;
  return L.divIcon({
    html: `<div style="
      background: #3b82f6;
      color: white;
      border-radius: 50%;
      width: ${size}px;
      height: ${size}px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: ${size > 40 ? 14 : 12}px;
      font-weight: 600;
      border: 2px solid white;
      box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    ">${count}</div>`,
    className: "custom-cluster-icon",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

// Location city photos view (route: /locations/:country/:city)
export function LocationCityPhotos() {
  const { country, city } = useParams<{ country: string; city: string }>();
  const navigate = useNavigate();
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      if (!country || !city) return;
      try {
        setLoading(true);
        const params: Record<string, string | number> = { page_size: 200 };
        params.country = decodeURIComponent(country);
        params.city = decodeURIComponent(city);
        const data = await api.getLocationPhotos(params);
        setPhotos(data.items);
        setTotal(data.total);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [country, city]);

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary, index: number) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
        openViewer(detail, photos, index);
      } catch {
        // ignore
      }
    },
    [openViewer, photos]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  const decodedCountry = country ? decodeURIComponent(country) : "";
  const decodedCity = city ? decodeURIComponent(city) : "";

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
        <button
          onClick={() => navigate(-1)}
          className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <MapPin className="w-5 h-5 text-gray-400" />
        <h1 className="text-lg font-semibold">
          {decodedCity}{decodedCountry ? `, ${decodedCountry}` : ""}
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {total} photo{total !== 1 ? "s" : ""}
          </span>
        </h1>
      </div>
      <PhotoGrid photos={photos} onPhotoClick={handlePhotoClick} />
    </div>
  );
}

// Location country cities view (route: /locations/:country)
export function LocationCountryCities() {
  const { country } = useParams<{ country: string }>();
  const navigate = useNavigate();
  const [cities, setCities] = useState<CityCount[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      if (!country) return;
      try {
        setLoading(true);
        const data = await api.getCities(decodeURIComponent(country));
        setCities(data);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [country]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  const decodedCountry = country ? decodeURIComponent(country) : "";

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
        <button
          onClick={() => navigate(-1)}
          className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <Globe className="w-5 h-5 text-gray-400" />
        <h1 className="text-lg font-semibold">
          {decodedCountry}
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {cities.length} cit{cities.length !== 1 ? "ies" : "y"}
          </span>
        </h1>
      </div>

      <div className="divide-y divide-gray-50">
        {cities.map((city) => (
          <button
            key={`${city.city}-${city.country}`}
            onClick={() => navigate(`/locations/${encodeURIComponent(decodedCountry)}/${encodeURIComponent(city.city)}`)}
            className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center gap-3">
              <MapPin className="w-4 h-4 text-gray-400" />
              <span className="text-sm font-medium">{city.city}</span>
            </div>
            <span className="text-sm text-gray-400">
              {city.count} photo{city.count !== 1 ? "s" : ""}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

// Locations main view with map/countries toggle (route: /locations)
export function Locations() {
  const [countries, setCountries] = useState<CountryCount[]>([]);
  const [mapPoints, setMapPoints] = useState<MapPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchParams, setSearchParams] = useSearchParams();
  const viewMode = (searchParams.get("view") as "map" | "countries") || "map";
  const navigate = useNavigate();

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const [countriesData, mapData] = await Promise.all([
          api.getCountries(),
          api.getMapPoints(),
        ]);
        setCountries(countriesData);
        setMapPoints(mapData);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const setViewMode = (mode: "map" | "countries") => {
    setSearchParams({ view: mode });
  };

  const handleMarkerClick = useCallback(
    (city: string | null, country: string | null) => {
      if (city && country) {
        navigate(`/locations/${encodeURIComponent(country)}/${encodeURIComponent(city)}`);
      } else if (country) {
        navigate(`/locations/${encodeURIComponent(country)}`);
      }
    },
    [navigate]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  // Map view
  if (viewMode === "map") {
    if (mapPoints.length === 0) {
      return (
        <div className="h-full flex flex-col">
          <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Map className="w-5 h-5 text-gray-400" />
              <h1 className="text-lg font-semibold">Map</h1>
            </div>
            <div className="flex gap-1">
              <button
                onClick={() => setViewMode("countries")}
                className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
                title="List view"
              >
                <List className="w-5 h-5 text-gray-400" />
              </button>
              <button
                className="p-2 rounded-lg bg-gray-100 transition-colors"
                title="Map view"
              >
                <Map className="w-5 h-5" />
              </button>
            </div>
          </div>
          <div className="flex-1 flex flex-col items-center justify-center text-gray-400 gap-2">
            <Map className="w-12 h-12 text-gray-300" />
            <p className="text-lg">No geotagged photos</p>
            <p className="text-sm">Photos with GPS data will appear on the map</p>
          </div>
        </div>
      );
    }

    const avgLat = mapPoints.reduce((sum, p) => sum + p.latitude, 0) / mapPoints.length;
    const avgLng = mapPoints.reduce((sum, p) => sum + p.longitude, 0) / mapPoints.length;

    return (
      <div className="h-full flex flex-col">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Map className="w-5 h-5 text-gray-400" />
            <h1 className="text-lg font-semibold">Map</h1>
          </div>
          <div className="flex gap-1">
            <button
              onClick={() => setViewMode("countries")}
              className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
              title="List view"
            >
              <List className="w-5 h-5 text-gray-400" />
            </button>
            <button
              className="p-2 rounded-lg bg-gray-100 transition-colors"
              title="Map view"
            >
              <Map className="w-5 h-5" />
            </button>
          </div>
        </div>
        <div className="flex-1 relative">
          <MapContainer
            center={[avgLat, avgLng]}
            zoom={4}
            className="h-full w-full z-0"
            scrollWheelZoom={true}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {mapPoints.map((point, i) => (
              <Marker
                key={i}
                position={[point.latitude, point.longitude]}
                icon={point.count > 1 ? createClusterIcon(point.count) : new L.Icon.Default()}
              >
                <Popup>
                  <div className="text-center min-w-[140px]">
                    <img
                      src={thumbnailUrl(point.representative_hash, 200)}
                      alt=""
                      className="w-32 h-24 object-cover rounded mb-2 cursor-pointer mx-auto"
                      onClick={() => handleMarkerClick(point.city, point.country)}
                    />
                    {(point.city || point.country) && (
                      <p className="text-sm font-medium">
                        {[point.city, point.country].filter(Boolean).join(", ")}
                      </p>
                    )}
                    <p className="text-xs text-gray-500">
                      {point.count} photo{point.count !== 1 ? "s" : ""}
                    </p>
                    <button 
                      onClick={() => handleMarkerClick(point.city, point.country)}
                      className="text-xs text-blue-500 hover:text-blue-700 mt-1"
                    >
                      View all photos
                    </button>
                  </div>
                </Popup>
              </Marker>
            ))}
          </MapContainer>
          <div className="absolute top-3 right-3 bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 shadow-md z-[1000]">
            <p className="text-xs text-gray-600">
              <span className="font-semibold">{mapPoints.length}</span> locations,{" "}
              <span className="font-semibold">{mapPoints.reduce((s, p) => s + p.count, 0)}</span> photos
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Countries list
  if (countries.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
        <Globe className="w-12 h-12 text-gray-300" />
        <p className="text-lg">No locations found</p>
        <p className="text-sm">Photos with GPS data will be grouped by location</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
        <h1 className="text-lg font-semibold">
          Locations
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {countries.length} countr{countries.length !== 1 ? "ies" : "y"}
          </span>
        </h1>
        {mapPoints.length > 0 && (
          <div className="flex gap-1">
            <button
              className="p-2 rounded-lg bg-gray-100 transition-colors"
              title="List view"
            >
              <List className="w-5 h-5" />
            </button>
            <button
              onClick={() => setViewMode("map")}
              className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
              title="Map view"
            >
              <Map className="w-5 h-5 text-gray-400" />
            </button>
          </div>
        )}
      </div>

      <div className="divide-y divide-gray-50">
        {countries.map((country) => (
          <button
            key={country.country}
            onClick={() => navigate(`/locations/${encodeURIComponent(country.country)}`)}
            className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center gap-3">
              <Globe className="w-4 h-4 text-gray-400" />
              <span className="text-sm font-medium">{country.country}</span>
            </div>
            <span className="text-sm text-gray-400">
              {country.count} photo{country.count !== 1 ? "s" : ""}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
