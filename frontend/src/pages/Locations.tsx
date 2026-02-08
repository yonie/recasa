import { useEffect, useState, useCallback } from "react";
import { api, type CountryCount, type CityCount, type PhotoSummary } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { Loader2, MapPin, ArrowLeft, Globe } from "lucide-react";

type ViewMode = "countries" | "cities" | "photos";

export function Locations() {
  const [countries, setCountries] = useState<CountryCount[]>([]);
  const [cities, setCities] = useState<CityCount[]>([]);
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [photosTotal, setPhotosTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>("countries");
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);
  const [selectedCity, setSelectedCity] = useState<string | null>(null);
  const openViewer = useStore((s) => s.openViewer);

  // Load countries
  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const data = await api.getCountries();
        setCountries(data);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const handleSelectCountry = useCallback(async (country: string) => {
    setSelectedCountry(country);
    setViewMode("cities");
    setLoading(true);
    try {
      const data = await api.getCities(country);
      setCities(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  const handleSelectCity = useCallback(
    async (city: string) => {
      setSelectedCity(city);
      setViewMode("photos");
      setLoading(true);
      try {
        const params: Record<string, string | number> = { page_size: 200 };
        if (selectedCountry) params.country = selectedCountry;
        if (city) params.city = city;
        const data = await api.getLocationPhotos(params);
        setPhotos(data.items);
        setPhotosTotal(data.total);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    },
    [selectedCountry]
  );

  const handleBack = useCallback(() => {
    if (viewMode === "photos") {
      setViewMode("cities");
      setSelectedCity(null);
      setPhotos([]);
    } else if (viewMode === "cities") {
      setViewMode("countries");
      setSelectedCountry(null);
      setCities([]);
    }
  }, [viewMode]);

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
        openViewer(detail);
      } catch {
        // ignore
      }
    },
    [openViewer]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  // Photos for a city
  if (viewMode === "photos" && selectedCity) {
    return (
      <div className="overflow-y-auto h-full">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
          <button
            onClick={handleBack}
            className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <MapPin className="w-5 h-5 text-gray-400" />
          <h1 className="text-lg font-semibold">
            {selectedCity}{selectedCountry ? `, ${selectedCountry}` : ""}
            <span className="ml-2 text-gray-400 font-normal text-sm">
              {photosTotal} photo{photosTotal !== 1 ? "s" : ""}
            </span>
          </h1>
        </div>
        <PhotoGrid photos={photos} onPhotoClick={handlePhotoClick} />
      </div>
    );
  }

  // Cities for a country
  if (viewMode === "cities" && selectedCountry) {
    return (
      <div className="overflow-y-auto h-full">
        <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
          <button
            onClick={handleBack}
            className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <Globe className="w-5 h-5 text-gray-400" />
          <h1 className="text-lg font-semibold">
            {selectedCountry}
            <span className="ml-2 text-gray-400 font-normal text-sm">
              {cities.length} cit{cities.length !== 1 ? "ies" : "y"}
            </span>
          </h1>
        </div>

        <div className="divide-y divide-gray-50">
          {cities.map((city) => (
            <button
              key={`${city.city}-${city.country}`}
              onClick={() => handleSelectCity(city.city)}
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
      <div className="px-4 py-3 border-b border-gray-100">
        <h1 className="text-lg font-semibold">
          Locations
          <span className="ml-2 text-gray-400 font-normal text-sm">
            {countries.length} countr{countries.length !== 1 ? "ies" : "y"}
          </span>
        </h1>
      </div>

      <div className="divide-y divide-gray-50">
        {countries.map((country) => (
          <button
            key={country.country}
            onClick={() => handleSelectCountry(country.country)}
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
