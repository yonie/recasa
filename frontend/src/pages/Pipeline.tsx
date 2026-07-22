import { useEffect, useState } from "react";
import {
  api,
  type PipelineStats,
  type ProcessingStats,
  type StageStats,
  type StageFailureItem,
} from "../api/client";
import {
  Activity,
  RotateCcw,
  FileImage,
  MapPin,
  Hash,
  User,
  Sparkles,
  Calendar,
  Play,
  Image,
  AlertTriangle,
  Loader2,
  Square,
  FolderOpen,
  Eye,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { clsx } from "clsx";

const QUEUE_ORDER = [
  "discovery",
  "exif",
  "geocoding",
  "thumbnails",
  "motion_photos",
  "hashing",
  "faces",
  "captioning",
  "events",
] as const;

const QUEUE_LABELS: Record<string, string> = {
  discovery: "File Discovery",
  exif: "EXIF Extraction",
  geocoding: "Geocoding",
  thumbnails: "Thumbnails",
  motion_photos: "Motion Photos",
  hashing: "Perceptual Hashing",
  faces: "Face Detection",
  captioning: "AI Captioning",
  events: "Event Detection",
};

const QUEUE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  discovery: FolderOpen,
  exif: FileImage,
  geocoding: MapPin,
  thumbnails: Image,
  motion_photos: Play,
  hashing: Hash,
  faces: User,
  captioning: Sparkles,
  events: Calendar,
};

// Stages that can be wiped and rebuilt from the danger zone
const REBUILDABLE: { stage: string; label: string; warning: string }[] = [
  { stage: "geocoding", label: "Rebuild geocoding", warning: "location names" },
  { stage: "hashing", label: "Rebuild hashes & duplicates", warning: "duplicate detection data" },
  { stage: "faces", label: "Rebuild faces", warning: "all detected faces and named people" },
  { stage: "captioning", label: "Rebuild captions", warning: "all AI captions" },
  { stage: "events", label: "Rebuild events", warning: "all detected events" },
];

function formatNumber(n: number): string {
  return n.toLocaleString();
}

/** Backend timestamps are UTC but serialized without a timezone marker. */
function parseUtc(timestamp: string): Date {
  const hasZone = /Z$|[+-]\d\d:?\d\d$/.test(timestamp);
  return new Date(hasZone ? timestamp : `${timestamp}Z`);
}

function formatWhen(timestamp: string): string {
  const d = parseUtc(timestamp);
  const now = new Date();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === now.toDateString()) return `Today ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return `Yesterday ${time}`;
  return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
}

function formatAgo(timestamp: string): string {
  const seconds = Math.max(0, (Date.now() - parseUtc(timestamp).getTime()) / 1000);
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return formatWhen(timestamp);
}

export function Pipeline() {
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [processingStats, setProcessingStats] = useState<ProcessingStats | null>(null);
  const [failures, setFailures] = useState<StageFailureItem[]>([]);
  const [wsState, setWsState] = useState<"connecting" | "connected" | "lost">("connecting");
  const [isTriggering, setIsTriggering] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [showFailures, setShowFailures] = useState(false);

  useEffect(() => {
    async function loadStats() {
      try {
        const [pipelineData, processingData, failuresData] = await Promise.all([
          api.getPipelineStatus(),
          api.getProcessingStats(),
          api.getPipelineFailures(),
        ]);
        setStats(pipelineData);
        setProcessingStats(processingData);
        setFailures(failuresData);
      } catch {
        // ignore
      }
    }
    loadStats();
    const interval = setInterval(loadStats, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    // Live updates over websocket, with automatic reconnect. A connection
    // that hasn't opened yet is "connecting" (not an error state) — "lost"
    // only after a previously-open connection drops. REST polling keeps the
    // page's data fresh either way.
    let ws: WebSocket | null = null;
    let retryTimer: number | undefined;
    let everConnected = false;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${protocol}//${window.location.host}/api/pipeline/ws`);
      ws.onopen = () => {
        everConnected = true;
        setWsState("connected");
      };
      ws.onclose = () => {
        if (disposed) return;
        setWsState(everConnected ? "lost" : "connecting");
        retryTimer = window.setTimeout(connect, 3000);
      };
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setStats(data);
          if (data.state === "idle") setIsStopping(false);
        } catch {
          // ignore
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);

  const handleRescan = async () => {
    if (isTriggering) return;
    setIsTriggering(true);
    try {
      await api.triggerScan();
    } catch {
      // ignore
    } finally {
      setIsTriggering(false);
    }
  };

  const handleStop = async () => {
    setIsStopping(true);
    try {
      await api.stopPipeline();
    } catch {
      // ignore
    }
  };

  const handleRebuildStage = async (stage: string, warning: string) => {
    if (!confirm(`This deletes ${warning} for ALL photos and rebuilds from scratch. Continue?`)) {
      return;
    }
    try {
      await api.clearStage(stage);
      await api.resumeProcessing();
    } catch {
      // ignore
    }
  };

  const handleClearIndex = async () => {
    if (
      !confirm(
        "This deletes the ENTIRE index: all photos, faces, people, tags, events and duplicates. " +
          "Your photo files are not touched, but everything must be re-indexed from scratch. Continue?"
      )
    ) {
      return;
    }
    if (isTriggering) return;
    setIsTriggering(true);
    try {
      await api.clearIndex();
    } catch {
      // ignore
    } finally {
      setIsTriggering(false);
    }
  };

  if (!stats || !processingStats) {
    return (
      <div className="flex items-center justify-center h-64">
        <Activity className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  const isActive = stats.state === "scanning" || stats.state === "processing";
  const totalPhotos = processingStats?.total_photos || 0;
  const watcher = stats.watcher;

  // Photos still waiting on some enabled stage, not counting terminal failures
  const pendingCount = (() => {
    if (!processingStats) return 0;
    let max = 0;
    for (const data of Object.values(processingStats.stages)) {
      if (data.enabled && data.total > 1) {
        const needed = Math.max(0, data.total - data.completed - data.failed);
        if (needed > max) max = needed;
      }
    }
    return max;
  })();

  const unreadableCount = new Set(failures.map((f) => f.file_hash)).size;

  return (
    <div className="p-6 max-w-[960px] mx-auto overflow-y-auto h-full">
      {/* Live-updates notice: only when a previously-open connection dropped */}
      {wsState === "lost" && (
        <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 flex items-center gap-2 text-sm text-amber-700">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          Live updates interrupted — reconnecting automatically. Shown status may lag a few seconds.
        </div>
      )}

      {/* Status hero */}
      {(
        <div className="mb-6 rounded-xl border border-gray-200 bg-white px-5 py-4 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3.5 min-w-0">
            {stats.state === "scanning" ? (
              <Loader2 className="w-8 h-8 text-blue-500 animate-spin shrink-0" />
            ) : isActive ? (
              <span className="relative flex w-8 h-8 items-center justify-center shrink-0">
                <span className="absolute w-4 h-4 rounded-full bg-blue-400 opacity-60 animate-ping" />
                <span className="relative w-3 h-3 rounded-full bg-blue-500" />
              </span>
            ) : (
              <span className="relative flex w-8 h-8 items-center justify-center shrink-0">
                <span className="absolute w-4 h-4 rounded-full bg-green-400 opacity-40 animate-[ping_4s_ease-in-out_infinite]" />
                <span className="relative w-3 h-3 rounded-full bg-green-500" />
              </span>
            )}
            <div className="min-w-0">
              <div className="font-semibold text-gray-900">
                {stats.state === "scanning"
                  ? "Checking for new photos…"
                  : isActive
                  ? "Processing photos"
                  : watcher && (watcher.sweep_interval > 0 || watcher.inotify_active)
                  ? "Watching for new photos"
                  : "Automatic detection is off"}
              </div>
              <div className="text-sm text-gray-500 truncate">
                {isActive && stats.state !== "scanning" ? (
                  "Working through the processing queues — the app stays usable meanwhile."
                ) : stats.state === "scanning" ? (
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
          </div>

          {isActive ? (
            <button
              onClick={handleStop}
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
              onClick={handleRescan}
              disabled={isTriggering}
              className="flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white disabled:opacity-50 rounded-lg transition-colors font-medium text-sm"
            >
              {isTriggering ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RotateCcw className="w-4 h-4" />
              )}
              Rescan library
            </button>
          )}
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        <div className="bg-white border border-gray-200 rounded-xl p-3.5">
          <div className="text-xs text-gray-500 mb-0.5">Indexed Photos</div>
          <div className="text-2xl font-bold text-gray-900 tabular-nums">
            {formatNumber(totalPhotos)}
          </div>
        </div>
        <div className={clsx("border rounded-xl p-3.5", pendingCount > 0 ? "bg-white border-blue-200" : "bg-gray-50/60 border-gray-200")}>
          <div className="text-xs text-gray-500 mb-0.5">Pending</div>
          <div className={clsx("text-2xl font-bold tabular-nums", pendingCount > 0 ? "text-blue-600" : "text-gray-300")}>
            {formatNumber(pendingCount)}
          </div>
        </div>
        <button
          onClick={() => setShowFailures((s) => !s)}
          disabled={unreadableCount === 0}
          className={clsx(
            "border rounded-xl p-3.5 text-left transition-colors",
            unreadableCount > 0
              ? "bg-amber-50 border-amber-200 hover:bg-amber-100 cursor-pointer"
              : "bg-gray-50/60 border-gray-200"
          )}
        >
          <div className={clsx("text-xs mb-0.5 flex items-center gap-1", unreadableCount > 0 ? "text-amber-700" : "text-gray-500")}>
            Unreadable
            {unreadableCount > 0 &&
              (showFailures ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />)}
          </div>
          <div className={clsx("text-2xl font-bold tabular-nums", unreadableCount > 0 ? "text-amber-600" : "text-gray-300")}>
            {formatNumber(unreadableCount)}
          </div>
        </button>
      </div>

      {/* Unreadable files drawer */}
      {showFailures && failures.length > 0 && (
        <div className="bg-white border border-amber-200 rounded-xl overflow-hidden mb-6">
          <div className="px-3 py-2 bg-amber-50 border-b border-amber-100 flex items-center gap-2">
            <Eye className="w-4 h-4 text-amber-600" />
            <span className="text-sm font-medium text-amber-800">
              Files that could not be processed
            </span>
            <span className="text-xs text-amber-600 ml-auto">
              won't be retried — fix or delete the file, or use a rebuild below
            </span>
          </div>
          <div className="max-h-64 overflow-y-auto">
            <table className="w-full text-xs">
              <tbody>
                {failures.map((f) => (
                  <tr key={`${f.file_hash}-${f.stage}`} className="border-b border-gray-50 last:border-0">
                    <td className="px-3 py-1.5 text-gray-700 max-w-72 truncate" title={f.file_path}>
                      {f.file_path}
                    </td>
                    <td className="px-3 py-1.5">
                      <span className="inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-600">
                        {QUEUE_LABELS[f.stage] || f.stage}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-amber-700 max-w-64 truncate" title={f.error || ""}>
                      {f.error}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Stage table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-6">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50/50">
              <th className="text-left font-medium text-gray-500 px-3 py-2">Stage</th>
              <th className="text-left font-medium text-gray-500 px-3 py-2 w-[130px]">Status</th>
              <th className="text-right font-medium text-gray-500 px-3 py-2 w-[130px]">Done</th>
              <th className="text-right font-medium text-gray-500 px-3 py-2 w-[64px]">Issues</th>
              <th className="font-medium text-gray-500 px-3 py-2 w-[180px]">Progress</th>
            </tr>
          </thead>
          <tbody>
            {QUEUE_ORDER.map((queueType) => {
              const Icon = QUEUE_ICONS[queueType] || Activity;
              const label = QUEUE_LABELS[queueType] || queueType;
              const stage: StageStats = processingStats?.stages[queueType] || {
                status: "pending", queued: 0, completed: 0, total: 0, enabled: true, failed: 0,
              };
              const isBatch = queueType === "events";

              const donePct = stage.total > 0 ? Math.floor((stage.completed / stage.total) * 100) : 0;
              const failedPct = stage.total > 0 ? Math.ceil((stage.failed / stage.total) * 100) : 0;
              const complete = stage.completed + stage.failed >= stage.total && stage.total > 0;

              return (
                <tr key={queueType} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/40">
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <Icon className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                      <span className="font-medium text-gray-900">{label}</span>
                      {stage.faces_found !== undefined && stage.faces_found > 0 && (
                        <span className="text-[10px] text-gray-400">
                          ({formatNumber(stage.faces_found)} faces)
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    {!stage.enabled ? (
                      <span className="inline-flex text-[10px] font-medium text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded-full">Disabled</span>
                    ) : stage.queued > 0 ? (
                      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded-full">
                        <Activity className="w-2.5 h-2.5 animate-pulse" />
                        Processing ({formatNumber(stage.queued)} queued)
                      </span>
                    ) : stage.failed > 0 ? (
                      <span className="inline-flex text-[10px] font-medium text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded-full">Done with exceptions</span>
                    ) : complete || isBatch ? (
                      <span className="inline-flex text-[10px] font-medium text-green-600 bg-green-50 px-1.5 py-0.5 rounded-full">Done</span>
                    ) : (
                      <span className="inline-flex text-[10px] font-medium text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded-full">Waiting</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums font-medium text-gray-900">
                    {isBatch ? (
                      <span className="text-gray-500">{formatNumber(stage.count || 0)} events</span>
                    ) : (
                      <>
                        {formatNumber(stage.completed)}
                        <span className="text-gray-400"> / {formatNumber(stage.total)}</span>
                      </>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {stage.failed > 0 ? (
                      <span className="font-medium text-amber-600">{formatNumber(stage.failed)}</span>
                    ) : (
                      <span className="text-gray-200">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {/* One structure for every row so all bars align exactly */}
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden flex">
                        {isBatch ? (
                          <div className="h-full w-full bg-green-500" />
                        ) : stage.enabled ? (
                          <>
                            <div className="h-full bg-green-500" style={{ width: `${donePct}%` }} />
                            {stage.failed > 0 && (
                              <div
                                className="h-full bg-amber-400"
                                style={{ width: `max(${failedPct}%, 6px)` }}
                              />
                            )}
                          </>
                        ) : null}
                      </div>
                      <span className="text-[10px] tabular-nums text-gray-500 w-8 text-right">
                        {isBatch
                          ? ""
                          : !stage.enabled
                          ? "off"
                          : complete && stage.failed === 0
                          ? "100%"
                          : `${donePct}%`}
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Danger zone */}
      <div className="border-t-2 border-red-200 pt-4 pb-8">
        <h2 className="text-sm font-semibold text-gray-700 mb-1">Destructive maintenance</h2>
        <p className="text-xs text-gray-500 mb-3">
          Rebuilds delete a stage's data for all photos and re-process from scratch. Your photo
          files are never touched.
        </p>
        <div className="flex flex-wrap gap-2 mb-4">
          {REBUILDABLE.map(({ stage, label, warning }) => (
            <button
              key={stage}
              onClick={() => handleRebuildStage(stage, warning)}
              disabled={isActive}
              className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-100 disabled:opacity-40 transition-colors"
            >
              {label}
            </button>
          ))}
        </div>
        <button
          onClick={handleClearIndex}
          disabled={isActive || isTriggering}
          className="text-xs text-red-600 hover:text-red-700 hover:underline disabled:opacity-40"
        >
          Delete entire index and start over…
        </button>
      </div>
    </div>
  );
}
