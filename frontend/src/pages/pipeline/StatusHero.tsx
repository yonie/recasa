import { Loader2, RotateCcw, Square } from "lucide-react";
import type { PipelineStats } from "../../api/client";
import { formatAgo } from "./time";

interface StatusHeroProps {
  stats: PipelineStats | undefined;
  isActive: boolean;
  isTriggering: boolean;
  isStopping: boolean;
  onRescan: () => void;
  onStop: () => void;
}

/** What the pipeline is doing right now, with Rescan or Stop. */
export function StatusHero({ stats, isActive, isTriggering, isStopping, onRescan, onStop }: StatusHeroProps) {
  return (
    <div className="mb-6 rounded-xl border border-gray-200 bg-white px-5 py-4 flex items-center justify-between gap-4 flex-wrap">
      <div className="flex items-center gap-3.5 min-w-0">
        {!stats ? (
          <>
            <span className="relative flex w-8 h-8 items-center justify-center shrink-0">
              <span className="w-3 h-3 rounded-full bg-gray-300 animate-pulse" />
            </span>
            <div className="min-w-0">
              <div className="font-semibold text-gray-900">Checking pipeline status…</div>
              <div className="text-sm text-gray-500 truncate">
                Fetching the current state of the library pipeline.
              </div>
            </div>
          </>
        ) : (
          <>
            <StateIcon state={stats.state} isActive={isActive} />
            <StateText stats={stats} isActive={isActive} />
          </>
        )}
      </div>

      {!stats ? null : isActive ? (
        <button
          onClick={onStop}
          disabled={isStopping}
          className="flex items-center gap-2 px-4 py-2 bg-red-50 hover:bg-red-100 text-red-700 disabled:opacity-50 rounded-lg transition-colors font-medium text-sm"
        >
          {isStopping ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" /> Stopping…
            </>
          ) : (
            <>
              <Square className="w-4 h-4" /> Stop
            </>
          )}
        </button>
      ) : (
        <button
          onClick={onRescan}
          disabled={isTriggering}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white disabled:opacity-50 rounded-lg transition-colors font-medium text-sm"
        >
          {isTriggering ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
          Rescan library
        </button>
      )}
    </div>
  );
}

function StateIcon({ state, isActive }: { state: PipelineStats["state"]; isActive: boolean }) {
  if (state === "scanning") return <Loader2 className="w-8 h-8 text-blue-500 animate-spin shrink-0" />;
  if (isActive) {
    return (
      <span className="relative flex w-8 h-8 items-center justify-center shrink-0">
        <span className="absolute w-4 h-4 rounded-full bg-blue-400 opacity-60 animate-ping" />
        <span className="relative w-3 h-3 rounded-full bg-blue-500" />
      </span>
    );
  }
  return (
    <span className="relative flex w-8 h-8 items-center justify-center shrink-0">
      <span className="absolute w-4 h-4 rounded-full bg-green-400 opacity-40 animate-[ping_4s_ease-in-out_infinite]" />
      <span className="relative w-3 h-3 rounded-full bg-green-500" />
    </span>
  );
}

function StateText({ stats, isActive }: { stats: PipelineStats; isActive: boolean }) {
  const watcher = stats.watcher;
  const scanning = stats.state === "scanning";
  return (
    <div className="min-w-0">
      <div className="font-semibold text-gray-900">
        {scanning
          ? "Checking for new photos…"
          : isActive
            ? "Processing photos"
            : watcher && (watcher.sweep_interval > 0 || watcher.inotify_active)
              ? "Watching for new photos"
              : "Automatic detection is off"}
      </div>
      <div className="text-sm text-gray-500 truncate">
        {isActive && !scanning ? (
          "Working through the processing queues — the app stays usable meanwhile."
        ) : scanning ? (
          "Sweeping the library for added, changed or removed files."
        ) : watcher && watcher.sweep_interval > 0 ? (
          <>
            New photos are picked up automatically (checked every{" "}
            {Math.round(watcher.sweep_interval / 60)} min).
            {watcher.last_scan_at && (
              <>
                {" "}Last check: {formatAgo(watcher.last_scan_at)}
                {watcher.last_scan_stats &&
                  (watcher.last_scan_stats.new > 0 ? (
                    <> — {watcher.last_scan_stats.new} new photos</>
                  ) : (
                    <> — nothing new</>
                  ))}
              </>
            )}
          </>
        ) : (
          "Set WATCH_INTERVAL to enable periodic checks, or use Rescan library."
        )}
      </div>
    </div>
  );
}
