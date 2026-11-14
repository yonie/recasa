import { useEffect, useMemo, useRef, useState } from "react";
import { CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import type L from "leaflet";
import { Footprints, Loader2 } from "lucide-react";
import "leaflet/dist/leaflet.css";
import { thumbnailUrl, type MapPoint, type TrailStop } from "../../api/client";
import { useOpenPhotoByHash } from "../../hooks/useOpenPhoto";
import { useStore } from "../../store/useStore";
import { formatStopDate } from "./formatStopDate";
import { activeStopIcon, clusterIcon, singlePhotoIcon } from "./icons";
import { CountdownRing, TimelineScrubber } from "./TimelineScrubber";
import { TrailControls } from "./TrailControls";
import { useHeroTrail } from "./useHeroTrail";

/** Flies the map to a position and opens the popup on the given marker. */
function FlyToAndOpen({
  position,
  zoom,
  markerRef,
  speed,
}: {
  position: [number, number];
  zoom: number;
  markerRef: React.RefObject<L.Marker | null>;
  speed: number;
}) {
  const map = useMap();
  const [lat, lng] = position;
  useEffect(() => {
    // Scale fly duration to fit within the stop interval, with a cap
    const flyDuration = Math.min(1.5, (speed / 1000) * 0.6);
    if (flyDuration < 0.3) {
      // Too fast for animation: just jump
      map.setView([lat, lng], zoom);
      markerRef.current?.openPopup();
    } else {
      map.flyTo([lat, lng], zoom, { duration: flyDuration });
      const t = setTimeout(() => {
        markerRef.current?.openPopup();
      }, flyDuration * 1000 + 100);
      return () => clearTimeout(t);
    }
  }, [map, lat, lng, zoom, markerRef, speed]);
  return null;
}

interface MapViewProps {
  /** Geotagged locations; the caller shows the empty state when there are none. */
  points: MapPoint[];
  onLocationClick: (city: string | null, country: string | null) => void;
}

export function MapView({ points, onLocationClick }: MapViewProps) {
  const viewerOpen = useStore((s) => s.viewerOpen);
  const openPhotoByHash = useOpenPhotoByHash();
  const t = useHeroTrail();
  const activeMarkerRef = useRef<L.Marker | null>(null);

  // Only the initial view: MapContainer ignores later center changes.
  const [center] = useState<[number, number]>(() => [
    points.reduce((sum, p) => sum + p.latitude, 0) / points.length,
    points.reduce((sum, p) => sum + p.longitude, 0) / points.length,
  ]);
  const photoTotal = useMemo(() => points.reduce((s, p) => s + p.count, 0), [points]);

  // Location markers are DOM elements, close to a thousand of them. Memoized
  // on the data so a re-render (opening the viewer, a trail state change)
  // doesn't push a fresh icon into every one of them.
  const locationMarkers = useMemo(
    () =>
      points.map((point, i) => (
        <Marker
          key={i}
          position={[point.latitude, point.longitude]}
          icon={point.count > 1 ? clusterIcon(point.count) : singlePhotoIcon}
        >
          <Popup>
            <div className="text-center min-w-[140px]">
              <img
                src={thumbnailUrl(point.representative_hash, 200)}
                alt=""
                className="w-32 h-24 object-cover rounded mb-2 cursor-pointer mx-auto"
                onClick={() => onLocationClick(point.city, point.country)}
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
                onClick={() => onLocationClick(point.city, point.country)}
                className="text-xs text-blue-500 hover:text-blue-700 mt-1"
              >
                View all photos
              </button>
            </div>
          </Popup>
        </Marker>
      )),
    [points, onLocationClick]
  );

  // Canvas-rendered stop dots, memoized on the trail alone so they aren't
  // rebuilt on every playback tick. Rendering thousands of DOM <Marker>s and
  // recreating them each frame was the FPS killer; CircleMarker draws into the
  // map's shared canvas (preferCanvas) and the memo keeps the layer stable.
  const trailDots = useMemo(
    () =>
      t.trail.map((stop, i) => (
        <CircleMarker
          key={`dot-${i}`}
          center={[stop.latitude, stop.longitude]}
          radius={3}
          pathOptions={{ color: "#2563eb", weight: 1, fillColor: "#3b82f6", fillOpacity: 0.8 }}
        />
      )),
    [t.trail]
  );

  // Trail polyline up to the current stop, and the dimmed remainder.
  const toLatLng = (s: TrailStop): [number, number] => [s.latitude, s.longitude];
  const visitedCoords = t.playMode ? t.trail.slice(0, t.currentStop + 1).map(toLatLng) : [];
  const futureCoords = t.playMode ? t.trail.slice(t.currentStop).map(toLatLng) : [];
  const activeStop = t.playMode ? t.trail[t.currentStop] : undefined;

  return (
    <div className="h-full relative z-0">
      <MapContainer center={center} zoom={4} className="h-full w-full" scrollWheelZoom={true} preferCanvas={true}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* Normal mode: show all cluster markers */}
        {!t.playMode && locationMarkers}

        {/* Play mode: trail line (future, dimmed) */}
        {futureCoords.length > 1 && (
          <Polyline
            positions={futureCoords}
            pathOptions={{ color: "#93c5fd", weight: 2, opacity: 0.4, dashArray: "6 4" }}
          />
        )}

        {/* Play mode: trail line (visited) */}
        {visitedCoords.length > 1 && (
          <Polyline positions={visitedCoords} pathOptions={{ color: "#3b82f6", weight: 3, opacity: 0.8 }} />
        )}

        {/* Play mode: canvas dots for all stops (memoized; see trailDots) */}
        {t.playMode && trailDots}

        {/* Play mode: active stop marker with photo popup */}
        {activeStop && (
          <>
            <Marker
              ref={activeMarkerRef}
              position={[activeStop.latitude, activeStop.longitude]}
              icon={activeStopIcon}
            >
              <Popup autoClose={false} closeOnClick={false} closeOnEscapeKey={false}>
                <div className="min-w-[180px]">
                  <div className="flex items-center gap-1.5 mb-1">
                    <p className="text-xs font-semibold text-gray-700">{formatStopDate(activeStop.date)}</p>
                    {t.playing && <CountdownRing key={t.currentStop} duration={t.speed} running={true} />}
                  </div>
                  {(activeStop.city || activeStop.country) && (
                    <p className="text-sm font-medium mb-2">
                      {[activeStop.city, activeStop.country].filter(Boolean).join(", ")}
                    </p>
                  )}
                  <div className="flex gap-1 flex-wrap">
                    {activeStop.photos.map((photo) => (
                      <img
                        key={photo.file_hash}
                        src={thumbnailUrl(photo.file_hash, 200)}
                        alt=""
                        className="w-20 h-16 object-cover rounded cursor-pointer"
                        onClick={() => openPhotoByHash(photo.file_hash)}
                      />
                    ))}
                  </div>
                  {activeStop.total_count > activeStop.photos.length && (
                    <p className="text-xs text-gray-400 mt-1">
                      +{activeStop.total_count - activeStop.photos.length} more
                    </p>
                  )}
                </div>
              </Popup>
            </Marker>
            <FlyToAndOpen
              key={`${t.currentStop}-${t.trail.length}`}
              position={[activeStop.latitude, activeStop.longitude]}
              zoom={10}
              markerRef={activeMarkerRef}
              speed={t.speed}
            />
          </>
        )}
      </MapContainer>

      {/* Overlays hide while the viewer is up, so they don't sit over the photo. */}
      {!viewerOpen && !t.playMode && (
        <>
          {/* Stats */}
          <div className="absolute top-3 right-3 bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 shadow-md z-[1001]">
            <p className="text-xs text-gray-600">
              <span className="font-semibold">{points.length}</span> locations,{" "}
              <span className="font-semibold">{photoTotal}</span> photos
            </p>
            <p className="text-[10px] text-gray-400 mt-0.5">Only photos with GPS data</p>
          </div>

          {/* Hero Trail launcher */}
          <button
            onClick={t.enter}
            disabled={t.loading}
            className="absolute bottom-6 right-6 z-[1001] bg-blue-500 hover:bg-blue-600 text-white rounded-full p-4 shadow-lg transition-colors disabled:opacity-50"
            title="Hero Trail"
          >
            {t.loading ? <Loader2 className="w-6 h-6 animate-spin" /> : <Footprints className="w-6 h-6" />}
          </button>
        </>
      )}

      {!viewerOpen && t.playMode && (
        <>
          <TrailControls trail={t} />
          {t.trail.length > 0 && (
            <TimelineScrubber
              trail={t.trail}
              currentStop={t.currentStop}
              onSeek={t.setCurrentStop}
              dateFrom={t.dateFrom}
              dateTo={t.dateTo}
              onDateFromChange={t.changeDateFrom}
              onDateToChange={t.changeDateTo}
            />
          )}
        </>
      )}
    </div>
  );
}
