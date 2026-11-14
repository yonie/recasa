import { Pause, Play, SkipBack, SkipForward, Square } from "lucide-react";
import type { HeroTrail } from "./useHeroTrail";
import { formatStopDate } from "./formatStopDate";

/** Bottom bar while a Hero Trail plays: step, play/pause, speed, exit. */
export function TrailControls({ trail: t }: { trail: HeroTrail }) {
  const activeStop = t.trail[t.currentStop];
  return (
    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-[1001] bg-white/95 backdrop-blur-sm rounded-xl shadow-lg px-4 py-3 flex items-center gap-3">
      {/* Progress info */}
      <div className="text-xs text-gray-600 min-w-[80px]">
        <span className="font-semibold">{t.currentStop + 1}</span>
        <span className="text-gray-400"> / {t.trail.length}</span>
      </div>

      {/* Controls */}
      <button
        onClick={() => t.setCurrentStop((p) => Math.max(0, p - 1))}
        disabled={t.currentStop === 0}
        className="p-1.5 rounded-full hover:bg-gray-100 disabled:opacity-30 transition-colors"
        title="Previous stop"
      >
        <SkipBack className="w-4 h-4 text-gray-700" />
      </button>

      <button
        onClick={() => t.setPlaying((p) => !p)}
        className="p-2.5 rounded-full bg-blue-500 hover:bg-blue-600 text-white transition-colors"
        title={t.playing ? "Pause" : "Play"}
      >
        {t.playing ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
      </button>

      <button
        onClick={() => t.setCurrentStop((p) => Math.min(t.trail.length - 1, p + 1))}
        disabled={t.currentStop >= t.trail.length - 1}
        className="p-1.5 rounded-full hover:bg-gray-100 disabled:opacity-30 transition-colors"
        title="Next stop"
      >
        <SkipForward className="w-4 h-4 text-gray-700" />
      </button>

      {/* Speed control */}
      <div className="border-l border-gray-200 pl-3 ml-1">
        <select
          value={t.speed}
          onChange={(e) => t.setSpeed(Number(e.target.value))}
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
        onClick={t.exit}
        className="p-1.5 rounded-full hover:bg-red-50 transition-colors"
        title="Exit play mode"
      >
        <Square className="w-4 h-4 text-red-500" />
      </button>

      {/* Current stop label */}
      {activeStop && (
        <div className="border-l border-gray-200 pl-3 ml-1 text-xs text-gray-600 max-w-[200px] truncate">
          {formatStopDate(activeStop.date)}
          {activeStop.city && ` - ${activeStop.city}`}
        </div>
      )}
    </div>
  );
}
