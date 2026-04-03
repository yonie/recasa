import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  Polyline,
  useMap,
} from "react-leaflet";
import L from "leaflet";
import {
  api,
  type MapPoint,
  type TrailStop,
  thumbnailUrl,
} from "../api/client";
import { useStore } from "../store/useStore";
import { Loader2, Map, Play, Pause, Square, SkipForward, SkipBack } from "lucide-react";
import "leaflet/dist/leaflet.css";

// Fix default marker icon issue with bundlers
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png",
  iconUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png",
  shadowUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
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

function createActiveStopIcon(): L.DivIcon {
  return L.divIcon({
    html: `<div style="
      background: #ef4444;
      border-radius: 50%;
      width: 18px;
      height: 18px;
      border: 3px solid white;
      box-shadow: 0 0 12px rgba(239,68,68,0.6);
    "></div>`,
    className: "active-stop-icon",
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function createTrailDotIcon(): L.DivIcon {
  return L.divIcon({
    html: `<div style="
      background: #3b82f6;
      border-radius: 50%;
      width: 8px;
      height: 8px;
      border: 2px solid white;
      box-shadow: 0 1px 3px rgba(0,0,0,0.3);
    "></div>`,
    className: "trail-dot-icon",
    iconSize: [8, 8],
    iconAnchor: [4, 4],
  });
}

/** Flies the map to a position and opens the popup on the given marker. */
function FlyToAndOpen({
  position,
  zoom,
  markerRef,
}: {
  position: [number, number];
  zoom: number;
  markerRef: React.RefObject<L.Marker | null>;
}) {
  const map = useMap();
  useEffect(() => {
    map.flyTo(position, zoom, { duration: 1.5 });
    // Open popup after fly animation settles
    const t = setTimeout(() => {
      markerRef.current?.openPopup();
    }, 1600);
    return () => clearTimeout(t);
  }, [map, position[0], position[1], zoom, markerRef]);
  return null;
}

/** Circular countdown timer that animates from full to empty over `duration` ms. */
function CountdownRing({
  duration,
  running,
  size = 18,
}: {
  duration: number;
  running: boolean;
  size?: number;
}) {
  const r = (size - 3) / 2;
  const circumference = 2 * Math.PI * r;
  return (
    <svg
      width={size}
      height={size}
      className="flex-shrink-0"
      style={{ transform: "rotate(-90deg)" }}
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="#e5e7eb"
        strokeWidth={2}
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="#3b82f6"
        strokeWidth={2}
        strokeDasharray={circumference}
        strokeDashoffset={0}
        strokeLinecap="round"
        style={
          running
            ? {
                animation: `countdown-ring ${duration}ms linear forwards`,
              }
            : { strokeDashoffset: 0 }
        }
      />
      <style>{`
        @keyframes countdown-ring {
          from { stroke-dashoffset: 0; }
          to { stroke-dashoffset: ${circumference}; }
        }
      `}</style>
    </svg>
  );
}

/** Horizontal timeline scrubber showing year ticks. Click or drag to seek. */
function TimelineScrubber({
  trail,
  currentStop,
  onSeek,
  dateFrom,
  dateTo,
  onDateFromChange,
  onDateToChange,
}: {
  trail: TrailStop[];
  currentStop: number;
  onSeek: (index: number) => void;
  dateFrom: string;
  dateTo: string;
  onDateFromChange: (v: string) => void;
  onDateToChange: (v: string) => void;
}) {
  const barRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  // Compute year tick positions
  const yearTicks = useMemo(() => {
    const ticks: { label: string; position: number }[] = [];
    let lastYear = "";
    const max = Math.max(trail.length - 1, 1);
    for (let i = 0; i < trail.length; i++) {
      const year = trail[i]!.date.slice(0, 4);
      if (year !== lastYear) {
        ticks.push({ label: year, position: (i / max) * 100 });
        lastYear = year;
      }
    }
    return ticks;
  }, [trail]);

  const seekFromEvent = useCallback(
    (clientX: number) => {
      if (!barRef.current) return;
      const rect = barRef.current.getBoundingClientRect();
      const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      const idx = Math.round(pct * (trail.length - 1));
      onSeek(idx);
    },
    [trail.length, onSeek]
  );

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      dragging.current = true;
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
      seekFromEvent(e.clientX);
    },
    [seekFromEvent]
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (dragging.current) seekFromEvent(e.clientX);
    },
    [seekFromEvent]
  );

  const onPointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  const progress =
    trail.length > 1 ? (currentStop / (trail.length - 1)) * 100 : 0;
  const active = trail[currentStop];
  const label = active
    ? `${active.date}${active.city ? " - " + active.city : ""}`
    : "";

  return (
    <div className="absolute top-0 left-0 right-0 z-[1000] bg-white/95 backdrop-blur-sm shadow-md select-none">
      {/* Header row: current stop label + date range pickers */}
      <div className="px-4 pt-2 pb-1 flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-gray-700 truncate">{label}</span>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className="text-[11px] text-gray-500">Date range:</span>
          <input
            type="date"
            value={dateFrom}
            max={new Date().toISOString().slice(0, 10)}
            onChange={(e) => onDateFromChange(e.target.value)}
            className="text-[11px] border border-gray-200 rounded px-1 py-0.5 w-[110px] text-gray-600"
          />
          <span className="text-gray-300 text-[11px]">-</span>
          <input
            type="date"
            value={dateTo}
            max={new Date().toISOString().slice(0, 10)}
            onChange={(e) => onDateToChange(e.target.value)}
            className="text-[11px] border border-gray-200 rounded px-1 py-0.5 w-[110px] text-gray-600"
          />
          <span className="text-xs text-gray-400 ml-1">
            {currentStop + 1}/{trail.length}
          </span>
        </div>
      </div>
      {/* Scrubber track */}
      <div
        ref={barRef}
        className="relative h-6 mx-4 mb-2 cursor-pointer"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        {/* Track background */}
        <div className="absolute top-[10px] left-0 right-0 h-1.5 bg-gray-200 rounded-full" />
        {/* Filled portion */}
        <div
          className="absolute top-[10px] left-0 h-1.5 bg-blue-500 rounded-full transition-[width] duration-200"
          style={{ width: `${progress}%` }}
        />
        {/* Year tick marks */}
        {yearTicks.map((tick) => (
          <div
            key={tick.label}
            className="absolute top-0 flex flex-col items-center"
            style={{ left: `${tick.position}%`, transform: "translateX(-50%)" }}
          >
            <span className="text-[9px] text-gray-400 leading-none">
              {tick.label}
            </span>
            <div className="w-px h-2 bg-gray-300 mt-0.5" />
          </div>
        ))}
        {/* Thumb */}
        <div
          className="absolute top-[6px] w-3 h-3 bg-blue-500 border-2 border-white rounded-full shadow transition-[left] duration-200"
          style={{ left: `${progress}%`, transform: "translateX(-50%)" }}
        />
      </div>
    </div>
  );
}

export function MapView({
  onLocationClick,
}: {
  onLocationClick?: (city: string | null, country: string | null) => void;
} = {}) {
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const openViewer = useStore((s) => s.openViewer);

  // Play mode state
  const [playMode, setPlayMode] = useState(false);
  const [trail, setTrail] = useState<TrailStop[]>([]);
  const [trailLoading, setTrailLoading] = useState(false);
  const [currentStop, setCurrentStop] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeMarkerRef = useRef<L.Marker | null>(null);
  const [speed, setSpeed] = useState(3000); // ms per stop
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

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

  // Enter play mode
  const enterPlayMode = useCallback(async () => {
    setTrailLoading(true);
    try {
      const params: { date_from?: string; date_to?: string } = {};
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      const data = await api.getTrail(params);
      if (data.length === 0) return;
      setTrail(data);
      if (!dateFrom) setDateFrom(data[0]!.date);
      if (!dateTo) setDateTo(data[data.length - 1]!.date);
      setCurrentStop(0);
      setPlayMode(true);
      setPlaying(true);
    } catch {
      // ignore
    } finally {
      setTrailLoading(false);
    }
  }, [dateFrom, dateTo]);

  // Reload trail with explicit date filters
  const reloadTrailWith = useCallback(async (from: string, to: string) => {
    setPlaying(false);
    setTrailLoading(true);
    try {
      const params: { date_from?: string; date_to?: string } = {};
      if (from) params.date_from = from;
      if (to) params.date_to = to;
      const data = await api.getTrail(params);
      if (data.length === 0) return;
      setTrail(data);
      setCurrentStop(0);
    } catch {
      // ignore
    } finally {
      setTrailLoading(false);
    }
  }, []);

  // Helper: add N days to a YYYY-MM-DD string
  const addDays = (d: string, n: number) => {
    const date = new Date(d + "T00:00:00");
    date.setDate(date.getDate() + n);
    return date.toISOString().slice(0, 10);
  };

  // Date change handlers with auto-clamping + immediate reload
  const handleDateFromChange = useCallback(
    (from: string) => {
      let to = dateTo;
      if (from && to && to <= from) {
        to = addDays(from, 1);
        setDateTo(to);
      }
      setDateFrom(from);
      if (playMode) reloadTrailWith(from, to);
    },
    [dateTo, playMode, reloadTrailWith]
  );

  const handleDateToChange = useCallback(
    (to: string) => {
      let from = dateFrom;
      if (to && from && from >= to) {
        from = addDays(to, -1);
        setDateFrom(from);
      }
      setDateTo(to);
      if (playMode) reloadTrailWith(from, to);
    },
    [dateFrom, playMode, reloadTrailWith]
  );

  // Exit play mode
  const exitPlayMode = useCallback(() => {
    setPlayMode(false);
    setPlaying(false);
    setTrail([]);
    setCurrentStop(0);
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  // Auto-advance when playing
  useEffect(() => {
    if (!playing || !playMode) return;
    timerRef.current = setTimeout(() => {
      setCurrentStop((prev) => {
        if (prev >= trail.length - 1) {
          setPlaying(false);
          return prev;
        }
        return prev + 1;
      });
    }, speed);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [playing, playMode, currentStop, speed, trail.length]);

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
  const avgLat =
    points.reduce((sum, p) => sum + p.latitude, 0) / points.length;
  const avgLng =
    points.reduce((sum, p) => sum + p.longitude, 0) / points.length;

  const activeStop = playMode ? trail[currentStop] : null;

  // Trail polyline up to current stop
  const trailCoords: [number, number][] = playMode
    ? trail.slice(0, currentStop + 1).map((s) => [s.latitude, s.longitude])
    : [];

  // Upcoming trail (dimmed)
  const futureCoords: [number, number][] = playMode
    ? trail.slice(currentStop).map((s) => [s.latitude, s.longitude])
    : [];

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr + "T00:00:00");
    return d.toLocaleDateString(undefined, {
      weekday: "short",
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

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

        {/* Normal mode: show all cluster markers */}
        {!playMode &&
          points.map((point, i) => (
            <Marker
              key={i}
              position={[point.latitude, point.longitude]}
              icon={
                point.count > 1
                  ? createClusterIcon(point.count)
                  : new L.Icon.Default()
              }
            >
              <Popup>
                <div className="text-center min-w-[140px]">
                  <img
                    src={thumbnailUrl(point.representative_hash, 200)}
                    alt=""
                    className="w-32 h-24 object-cover rounded mb-2 cursor-pointer mx-auto"
                    onClick={() =>
                      onLocationClick
                        ? onLocationClick(point.city, point.country)
                        : handleMarkerClick(point.representative_hash)
                    }
                  />
                  {(point.city || point.country) && (
                    <p className="text-sm font-medium">
                      {[point.city, point.country].filter(Boolean).join(", ")}
                    </p>
                  )}
                  <p className="text-xs text-gray-500">
                    {point.count} photo{point.count !== 1 ? "s" : ""}
                  </p>
                  {onLocationClick && (
                    <button
                      onClick={() => onLocationClick(point.city, point.country)}
                      className="text-xs text-blue-500 hover:text-blue-700 mt-1"
                    >
                      View all photos
                    </button>
                  )}
                </div>
              </Popup>
            </Marker>
          ))}

        {/* Play mode: trail line (future, dimmed) */}
        {playMode && futureCoords.length > 1 && (
          <Polyline
            positions={futureCoords}
            pathOptions={{
              color: "#93c5fd",
              weight: 2,
              opacity: 0.4,
              dashArray: "6 4",
            }}
          />
        )}

        {/* Play mode: trail line (visited) */}
        {playMode && trailCoords.length > 1 && (
          <Polyline
            positions={trailCoords}
            pathOptions={{
              color: "#3b82f6",
              weight: 3,
              opacity: 0.8,
            }}
          />
        )}

        {/* Play mode: small dots for all stops */}
        {playMode &&
          trail.map((stop, i) =>
            i !== currentStop ? (
              <Marker
                key={`dot-${i}`}
                position={[stop.latitude, stop.longitude]}
                icon={createTrailDotIcon()}
              />
            ) : null
          )}

        {/* Play mode: active stop marker with photo popup */}
        {activeStop && (
          <>
            <Marker
              ref={activeMarkerRef}
              position={[activeStop.latitude, activeStop.longitude]}
              icon={createActiveStopIcon()}
            >
              <Popup autoClose={false} closeOnClick={false}>
                <div className="min-w-[180px]">
                  <div className="flex items-center gap-1.5 mb-1">
                    <p className="text-xs font-semibold text-gray-700">
                      {formatDate(activeStop.date)}
                    </p>
                    <CountdownRing
                      key={currentStop}
                      duration={speed}
                      running={playing}
                    />
                  </div>
                  {(activeStop.city || activeStop.country) && (
                    <p className="text-sm font-medium mb-2">
                      {[activeStop.city, activeStop.country]
                        .filter(Boolean)
                        .join(", ")}
                    </p>
                  )}
                  <div className="flex gap-1 flex-wrap">
                    {activeStop.photos.map((photo) => (
                      <img
                        key={photo.file_hash}
                        src={thumbnailUrl(photo.file_hash, 200)}
                        alt=""
                        className="w-20 h-16 object-cover rounded cursor-pointer"
                        onClick={() => handleMarkerClick(photo.file_hash)}
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
              position={[activeStop.latitude, activeStop.longitude]}
              zoom={10}
              markerRef={activeMarkerRef}
            />
          </>
        )}
      </MapContainer>

      {/* Stats overlay (normal mode) */}
      {!playMode && (
        <div className="absolute top-3 right-3 bg-white/90 backdrop-blur-sm rounded-lg px-3 py-2 shadow-md z-[1000]">
          <p className="text-xs text-gray-600">
            <span className="font-semibold">{points.length}</span> locations,{" "}
            <span className="font-semibold">
              {points.reduce((s, p) => s + p.count, 0)}
            </span>{" "}
            photos
          </p>
        </div>
      )}

      {/* Hero Trail launcher (normal mode) */}
      {!playMode && (
        <button
          onClick={enterPlayMode}
          disabled={trailLoading}
          className="absolute bottom-6 right-6 z-[1000] bg-blue-500 hover:bg-blue-600 text-white rounded-full p-4 shadow-lg transition-colors disabled:opacity-50"
          title="Play Hero Trail"
        >
          {trailLoading ? (
            <Loader2 className="w-6 h-6 animate-spin" />
          ) : (
            <Play className="w-6 h-6" />
          )}
        </button>
      )}

      {/* Play mode controls */}
      {playMode && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-[1000] bg-white/95 backdrop-blur-sm rounded-xl shadow-lg px-4 py-3 flex items-center gap-3">
          {/* Progress info */}
          <div className="text-xs text-gray-600 min-w-[80px]">
            <span className="font-semibold">{currentStop + 1}</span>
            <span className="text-gray-400"> / {trail.length}</span>
          </div>

          {/* Controls */}
          <button
            onClick={() => setCurrentStop((p) => Math.max(0, p - 1))}
            disabled={currentStop === 0}
            className="p-1.5 rounded-full hover:bg-gray-100 disabled:opacity-30 transition-colors"
            title="Previous stop"
          >
            <SkipBack className="w-4 h-4 text-gray-700" />
          </button>

          <button
            onClick={() => setPlaying((p) => !p)}
            className="p-2.5 rounded-full bg-blue-500 hover:bg-blue-600 text-white transition-colors"
            title={playing ? "Pause" : "Play"}
          >
            {playing ? (
              <Pause className="w-5 h-5" />
            ) : (
              <Play className="w-5 h-5" />
            )}
          </button>

          <button
            onClick={() =>
              setCurrentStop((p) => Math.min(trail.length - 1, p + 1))
            }
            disabled={currentStop >= trail.length - 1}
            className="p-1.5 rounded-full hover:bg-gray-100 disabled:opacity-30 transition-colors"
            title="Next stop"
          >
            <SkipForward className="w-4 h-4 text-gray-700" />
          </button>

          {/* Speed control */}
          <div className="border-l border-gray-200 pl-3 ml-1">
            <select
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
              className="text-xs bg-transparent text-gray-600 border border-gray-200 rounded px-1.5 py-1"
            >
              <option value={5000}>Slow</option>
              <option value={3000}>Normal</option>
              <option value={1500}>Fast</option>
              <option value={800}>Rapid</option>
            </select>
          </div>

          {/* Stop button */}
          <button
            onClick={exitPlayMode}
            className="p-1.5 rounded-full hover:bg-red-50 transition-colors"
            title="Exit play mode"
          >
            <Square className="w-4 h-4 text-red-500" />
          </button>

          {/* Current stop label */}
          {activeStop && (
            <div className="border-l border-gray-200 pl-3 ml-1 text-xs text-gray-600 max-w-[200px] truncate">
              {formatDate(activeStop.date)}
              {activeStop.city && ` - ${activeStop.city}`}
            </div>
          )}
        </div>
      )}

      {/* Timeline scrubber at top */}
      {playMode && trail.length > 0 && (
        <TimelineScrubber
          trail={trail}
          currentStop={currentStop}
          onSeek={setCurrentStop}
          dateFrom={dateFrom}
          dateTo={dateTo}
          onDateFromChange={handleDateFromChange}
          onDateToChange={handleDateToChange}
        />
      )}
    </div>
  );
}
