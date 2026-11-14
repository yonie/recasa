import { useCallback, useMemo, useRef } from "react";
import type { TrailStop } from "../../api/client";

/** Circular countdown timer that animates from full to empty over `duration` ms. */
export function CountdownRing({
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

/** A button that displays a formatted date and opens a native date picker on click. */
function DatePickerButton({
  value,
  min,
  max,
  onChange,
}: {
  value: string;
  min?: string;
  max: string;
  onChange: (v: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const label = value
    ? new Date(value + "T00:00:00").toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : "Select";
  return (
    <span className="relative inline-block">
      <button
        onClick={() => inputRef.current?.showPicker()}
        className="text-[11px] font-medium text-blue-600 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 rounded px-1.5 py-0.5 transition-colors"
      >
        {label}
      </button>
      <input
        ref={inputRef}
        type="date"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(e.target.value)}
        className="absolute inset-0 opacity-0 w-0 h-0 pointer-events-none"
        tabIndex={-1}
      />
    </span>
  );
}

/** Horizontal timeline scrubber showing year ticks. Click or drag to seek. */
export function TimelineScrubber({
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
    <div className="absolute top-0 left-0 right-0 z-[1001] bg-white/95 backdrop-blur-sm shadow-md select-none">
      {/* Header row: current stop label + date range pickers */}
      <div className="px-4 pt-2 pb-1 flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-gray-700 truncate">{label}</span>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <span className="text-[11px] text-gray-500">Date range:</span>
          <DatePickerButton
            value={dateFrom}
            max={dateTo || new Date().toISOString().slice(0, 10)}
            onChange={onDateFromChange}
          />
          <span className="text-gray-300 text-[11px]">-</span>
          <DatePickerButton
            value={dateTo}
            min={dateFrom}
            max={new Date().toISOString().slice(0, 10)}
            onChange={onDateToChange}
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
