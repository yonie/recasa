import { useEffect, useState, useCallback } from "react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import { api, type MapPoint, thumbnailUrl } from "../api/client";
import { useStore } from "../store/useStore";
import { Loader2, Map } from "lucide-react";
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

export function MapView() {
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const data = await api.getMapPoints();
        setPoints(data);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const handleMarkerClick = useCallback(
    async (hash: string) => {
      try {
        const detail = await api.getPhoto(hash);
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

  if (points.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-gray-400 gap-2">
        <Map className="w-12 h-12 text-gray-300" />
        <p className="text-lg">No geotagged photos</p>
        <p className="text-sm">Photos with GPS data will appear on the map</p>
      </div>
    );
  }

  // Calculate map center from all points
  const avgLat = points.reduce((sum, p) => sum + p.latitude, 0) / points.length;
  const avgLng = points.reduce((sum, p) => sum + p.longitude, 0) / points.length;

  return (
    <div className="h-full relative">
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
        {points.map((point, i) => (
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
                  onClick={() => handleMarkerClick(point.representative_hash)}
                />
                {(point.city || point.country) && (
                  <p className="text-sm font-medium">
                    {[point.city, point.country].filter(Boolean).join(", ")}
                  </p>
                )}
                <p className="text-xs text-gray-500">
                  {point.count} photo{point.count !== 1 ? "s" : ""}
                </p>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>

      {/* Stats overlay */}
      <div className="absolute top-3 right-3 bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 shadow-md z-[1000]">
        <p className="text-xs text-gray-600">
          <span className="font-semibold">{points.length}</span> locations,{" "}
          <span className="font-semibold">{points.reduce((s, p) => s + p.count, 0)}</span> photos
        </p>
      </div>
    </div>
  );
}
