import { useEffect, useState } from "react";
import { api, type QueueStats, type PipelineStats, type ProcessingStats } from "../api/client";
import {
  Activity,
  RotateCcw,
  Trash2,
  FileImage,
  MapPin,
  Hash,
  User,
  Sparkles,
  Calendar,
  Play,
  Image,
  CheckCircle2,
  AlertCircle,
  Clock,
  Check,
  Loader2,
  Square,
} from "lucide-react";

const QUEUE_ORDER = [
  "exif",
  "geocoding",
  "thumbnails",
  "motion_photos",
  "hashing",
  "faces",
  "captioning",
  "events",
];

const QUEUE_LABELS: Record<string, string> = {
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
  exif: FileImage,
  geocoding: MapPin,
  thumbnails: Image,
  motion_photos: Play,
  hashing: Hash,
  faces: User,
  captioning: Sparkles,
  events: Calendar,
};

const STAGE_COLORS: Record<string, { bg: string; bar: string; text: string; light: string }> = {
  exif: { bg: "bg-blue-50", bar: "bg-blue-500", text: "text-blue-700", light: "bg-blue-100" },
  geocoding: { bg: "bg-cyan-50", bar: "bg-cyan-500", text: "text-cyan-700", light: "bg-cyan-100" },
  thumbnails: { bg: "bg-teal-50", bar: "bg-teal-500", text: "text-teal-700", light: "bg-teal-100" },
  motion_photos: { bg: "bg-emerald-50", bar: "bg-emerald-500", text: "text-emerald-700", light: "bg-emerald-100" },
  hashing: { bg: "bg-amber-50", bar: "bg-amber-500", text: "text-amber-700", light: "bg-amber-100" },
  faces: { bg: "bg-rose-50", bar: "bg-rose-500", text: "text-rose-700", light: "bg-rose-100" },
  captioning: { bg: "bg-pink-50", bar: "bg-pink-500", text: "text-pink-700", light: "bg-pink-100" },
  events: { bg: "bg-indigo-50", bar: "bg-indigo-500", text: "text-indigo-700", light: "bg-indigo-100" },
};

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function formatNumber(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toLocaleString();
}

function StageBadge({ queue }: { queue: QueueStats }) {
  const isActive = queue.processing > 0;
  const hasPending = queue.pending > 0;
  if (isActive) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded-full">
        <Activity className="w-2.5 h-2.5 animate-pulse" />
        Active
      </span>
    );
  }
  if (hasPending) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded-full">
        <Clock className="w-2.5 h-2.5" />
        Queued
      </span>
    );
  }
  if (queue.completed_total > 0) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-green-600 bg-green-50 px-1.5 py-0.5 rounded-full">
        <CheckCircle2 className="w-2.5 h-2.5" />
        Done
      </span>
    );
  }
  return <span className="text-[10px] text-gray-300">-</span>;
}

export function Pipeline() {
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [processingStats, setProcessingStats] = useState<ProcessingStats | null>(null);
  const [connected, setConnected] = useState(false);
  const [isTriggering, setIsTriggering] = useState(false);
  const [isStopping, setIsStopping] = useState(false);

  useEffect(() => {
    async function loadStats() {
      try {
        const [pipelineData, processingData] = await Promise.all([
          api.getPipelineStatus(),
          api.getProcessingStats(),
        ]);
        setStats(pipelineData);
        setProcessingStats(processingData);
      } catch {
        // ignore
      }
    }
    loadStats();
    const interval = setInterval(loadStats, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/pipeline/ws`);
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setStats(data);
        // Reset stopping state when pipeline becomes idle
        if (data.state === "idle") {
          setIsStopping(false);
        }
      } catch {
        // ignore
      }
    };
    return () => ws.close();
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

  const handleClearIndex = async () => {
    if (!confirm("This will delete all indexed data. Continue?")) return;
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

  if (!stats) {
    return (
      <div className="flex items-center justify-center h-64">
        <Activity className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  const isActive = stats.state === "scanning" || stats.state === "processing";

  const totalPhotos = processingStats?.total_photos || 0;

  // Calculate photos needing any processing stage
  const photosNeedingWork = (() => {
    if (!processingStats) return 0;
    let maxNeeded = 0;
    for (const data of Object.values(processingStats.stages)) {
      if (data.enabled && data.total > 0) {
        const needed = data.total - data.completed;
        if (needed > maxNeeded) maxNeeded = needed;
      }
    }
    return maxNeeded;
  })();

  // Map queue types to processing stats keys
  const getStageStats = (queueType: string): { completed: number; total: number } => {
    if (!processingStats) return { completed: 0, total: 0 };
    const keyMap: Record<string, string> = {
      motion_photos: "exif",
      events: "events",
    };
    const key = keyMap[queueType] || queueType;
    return processingStats.stages[key as keyof typeof processingStats.stages] || { completed: 0, total: processingStats.total_photos };
  };

  return (
    <div className="p-6 max-w-[960px] mx-auto">
      {/* Status Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Pipeline</h1>
          <div className="text-sm text-gray-500 mt-0.5">
            {stats.state === "scanning" && stats.scan_progress && (
              <span className="flex items-center gap-2 text-blue-600">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                {stats.scan_progress.discovery_phase === "collecting_files" ? (
                  <>Collecting files ({formatNumber(stats.scan_progress.discovery_files_collected)} found)</>
                ) : (
                  <>Scanning {formatNumber(stats.scan_progress.scanned_files)} / {formatNumber(stats.scan_progress.total_files)} files</>
                )}
              </span>
            )}
            {stats.state === "processing" && stats.processing_progress && (
              <span className="flex items-center gap-2">
                <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                Processing {formatNumber(stats.processing_progress.files_processing)} photos ({formatDuration(stats.processing_progress.elapsed_seconds)})
              </span>
            )}
            {stats.state === "done" && stats.completion_summary && (
              <span className="flex items-center gap-2 text-green-600">
                <Check className="w-3.5 h-3.5" />
                {stats.completion_summary.scan_stats ? (
                  <>
                    Scanned {formatNumber(stats.completion_summary.scan_stats.total || 0)} files:
                    {" "}{stats.completion_summary.scan_stats.new || 0} new,
                    {" "}{stats.completion_summary.scan_stats.updated || 0} updated,
                    {" "}{stats.completion_summary.scan_stats.skipped || 0} unchanged
                    {" "} ({formatDuration(stats.completion_summary.elapsed_seconds)})
                  </>
                ) : (
                  <>Completed in {formatDuration(stats.completion_summary.elapsed_seconds)}</>
                )}
              </span>
            )}
            {stats.state === "idle" && (
              <span className="flex items-center gap-2 text-gray-400">
                <span className="w-2 h-2 bg-gray-300 rounded-full" />
                Ready
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 text-sm">
          {isActive ? (
            <button
              onClick={handleStop}
              disabled={isStopping}
              className="flex items-center gap-2 px-3 py-1.5 bg-red-50 hover:bg-red-100 text-red-700 disabled:opacity-50 rounded-lg transition-colors min-w-[100px] justify-center"
            >
              {isStopping ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Stopping...
                </>
              ) : (
                <>
                  <Square className="w-4 h-4" />
                  Stop
                </>
              )}
            </button>
          ) : (
            <button
              onClick={handleRescan}
              disabled={isTriggering}
              className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 rounded-lg transition-colors text-gray-700"
            >
              {isTriggering ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RotateCcw className="w-4 h-4" />
              )}
              Rescan
            </button>
          )}
          <button
            onClick={handleClearIndex}
            disabled={isTriggering || isActive}
            className="flex items-center gap-2 px-3 py-1.5 bg-red-50 hover:bg-red-100 text-red-700 disabled:opacity-50 rounded-lg transition-colors"
          >
            <Trash2 className="w-4 h-4" />
            Clear index
          </button>
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-red-400"}`} />
            <span className="text-xs text-gray-400">{connected ? "Live" : "Offline"}</span>
          </div>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        <div className="bg-white border border-gray-200 rounded-xl p-3.5">
          <div className="text-xs text-gray-500 mb-0.5">Indexed Photos</div>
          <div className="text-2xl font-bold text-gray-900 tabular-nums">
            {formatNumber(totalPhotos)}
          </div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-3.5">
          <div className="text-xs text-gray-500 mb-0.5">{isActive ? "Queued" : "Need Processing"}</div>
          <div className="text-2xl font-bold text-blue-600 tabular-nums">
            {formatNumber(photosNeedingWork)}
          </div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-3.5">
          <div className="text-xs text-gray-500 mb-0.5">Errors</div>
          <div className={`text-2xl font-bold tabular-nums ${stats.error_count > 0 ? "text-red-600" : "text-gray-400"}`}>
            {stats.error_count || 0}
          </div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-3.5">
          <div className="text-xs text-gray-500 mb-0.5">Status</div>
          <div className="text-lg font-semibold text-gray-900">
            {isActive ? (
              <span className="flex items-center gap-1.5 text-green-600">
                <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                Processing
              </span>
            ) : (
              <span className="text-gray-400">Idle</span>
            )}
          </div>
        </div>
      </div>

      {/* Queue Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden mb-4">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50/50">
              <th className="text-left font-medium text-gray-500 px-3 py-2">Stage</th>
              <th className="text-left font-medium text-gray-500 px-3 py-2 w-[72px]">Status</th>
              <th className="text-right font-medium text-gray-500 px-3 py-2 w-[72px]">Done</th>
              <th className="text-right font-medium text-gray-500 px-3 py-2 w-[56px]">Failed</th>
              <th className="text-right font-medium text-gray-500 px-3 py-2 w-[64px]">Pending</th>
              <th className="font-medium text-gray-500 px-3 py-2 w-[160px]">Progress</th>
            </tr>
          </thead>
          <tbody>
            {QUEUE_ORDER.map((queueType) => {
              const queue = stats.queues[queueType];
              if (!queue) return null;
              const Icon = QUEUE_ICONS[queueType] || Activity;
              const label = QUEUE_LABELS[queueType] || queueType;
              const colors = STAGE_COLORS[queueType] ?? STAGE_COLORS.discovery!;
              const stageStats = getStageStats(queueType);
              const pct = stageStats.total > 0 ? Math.min(100, Math.round((stageStats.completed / stageStats.total) * 100)) : 0;
              return (
                <tr key={queueType} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/40">
                  <td className="px-3 py-1.5">
                    <div className="flex items-center gap-2">
                      <Icon className={`w-3.5 h-3.5 ${colors.text} shrink-0`} />
                      <span className="font-medium text-gray-900">{label}</span>
                    </div>
                  </td>
                  <td className="px-3 py-1.5">
                    <StageBadge queue={queue} />
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums font-medium text-gray-900">
                    {formatNumber(stageStats.completed)}<span className="text-gray-400">/{formatNumber(stageStats.total)}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {queue.failed_total > 0 ? (
                      <span className="font-medium text-red-500">{formatNumber(queue.failed_total)}</span>
                    ) : (
                      <span className="text-gray-300">-</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {queue.pending + queue.processing > 0 ? (
                      <span className="font-medium text-gray-600">{formatNumber(queue.pending + queue.processing)}</span>
                    ) : (
                      <span className="text-gray-300">-</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className={`h-full ${colors.bar} rounded-full transition-all duration-700 ease-out ${queue.processing > 0 ? "animate-pulse" : ""}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="text-[10px] tabular-nums text-gray-500 w-8 text-right">{pct}%</span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Error Log */}
      {stats.error_log && stats.error_log.length > 0 && (
        <div className="bg-white border border-red-200 rounded-xl overflow-hidden">
          <div className="px-3 py-2 bg-red-50 border-b border-red-100 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-red-500" />
            <span className="text-sm font-medium text-red-700">Recent Errors</span>
            <span className="text-xs text-red-500 ml-auto">{stats.error_log.length}</span>
          </div>
          <div className="max-h-48 overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50 sticky top-0">
                  <th className="text-left font-medium text-gray-500 px-3 py-1.5">Time</th>
                  <th className="text-left font-medium text-gray-500 px-3 py-1.5">Stage</th>
                  <th className="text-left font-medium text-gray-500 px-3 py-1.5">File</th>
                  <th className="text-left font-medium text-gray-500 px-3 py-1.5">Error</th>
                </tr>
              </thead>
              <tbody>
                {stats.error_log.map((err, i) => (
                  <tr key={i} className="border-b border-gray-50 last:border-0 hover:bg-red-50/30">
                    <td className="px-3 py-1.5 text-gray-500 tabular-nums whitespace-nowrap">
                      {new Date(err.timestamp).toLocaleTimeString()}
                    </td>
                    <td className="px-3 py-1.5">
                      <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-700">
                        {err.queue}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-gray-600 max-w-48 truncate" title={err.file_path || err.file_hash}>
                      {err.file_path ? err.file_path.split(/[\\/]/).pop() : err.file_hash.slice(0, 12)}
                    </td>
                    <td className="px-3 py-1.5 text-red-600 max-w-64 truncate" title={err.error}>
                      {err.error}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}