import { useEffect, useState } from "react";
import { api, type QueueStats } from "../api/client";
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
  Search,
  CheckCircle2,
  AlertCircle,
  Clock,
  Check,
} from "lucide-react";

interface PipelineStats {
  is_running: boolean;
  status: "idle" | "processing" | "done";
  total_files_discovered: number;
  total_files_completed: number;
  start_time: string | null;
  uptime_seconds: number;
  queues: Record<string, QueueStats>;
  flow: Record<string, string[]>;
}

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
];

const QUEUE_LABELS: Record<string, string> = {
  discovery: "Discovery",
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
  discovery: Search,
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
  discovery: { bg: "bg-violet-50", bar: "bg-violet-500", text: "text-violet-700", light: "bg-violet-100" },
  exif: { bg: "bg-blue-50", bar: "bg-blue-500", text: "text-blue-700", light: "bg-blue-100" },
  geocoding: { bg: "bg-cyan-50", bar: "bg-cyan-500", text: "text-cyan-700", light: "bg-cyan-100" },
  thumbnails: { bg: "bg-teal-50", bar: "bg-teal-500", text: "text-teal-700", light: "bg-teal-100" },
  motion_photos: { bg: "bg-emerald-50", bar: "bg-emerald-500", text: "text-emerald-700", light: "bg-emerald-100" },
  hashing: { bg: "bg-amber-50", bar: "bg-amber-500", text: "text-amber-700", light: "bg-amber-100" },
  faces: { bg: "bg-rose-50", bar: "bg-rose-500", text: "text-rose-700", light: "bg-rose-100" },
  captioning: { bg: "bg-pink-50", bar: "bg-pink-500", text: "text-pink-700", light: "bg-pink-100" },
  events: { bg: "bg-indigo-50", bar: "bg-indigo-500", text: "text-indigo-700", light: "bg-indigo-100" },
};

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }
  if (seconds < 86400) {
    const h = Math.floor(seconds / 3600);
    const m = Math.round((seconds % 3600) / 60);
    return `${h}h ${m}m`;
  }
  const d = Math.floor(seconds / 86400);
  const h = Math.round((seconds % 86400) / 3600);
  return `${d}d ${h}h`;
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
  const [connected, setConnected] = useState(false);
  const [isTriggering, setIsTriggering] = useState(false);

  // Load initial stats
  useEffect(() => {
    async function loadStats() {
      try {
        const data = await api.getPipelineStatus();
        setStats(data as PipelineStats);
      } catch {
        // ignore
      }
    }

    loadStats();
    const interval = setInterval(loadStats, 3000);
    return () => clearInterval(interval);
  }, []);

  // WebSocket for real-time updates
  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/pipeline/ws`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (event) => {
      try {
        setStats(JSON.parse(event.data));
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

  const handleRebuildIndex = async () => {
    if (!confirm("This will delete all indexed data and rebuild from scratch. Continue?")) return;
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

  const totalInProgress = Math.max(0, Object.values(stats.queues).reduce(
    (acc, q) => acc + q.pending + q.processing,
    0
  ));

  const totalCompleted = stats.total_files_completed;
  const totalFailed = Object.values(stats.queues).reduce(
    (acc, q) => acc + q.failed_total,
    0
  );

  const maxCompleted = Math.max(
    ...Object.values(stats.queues).map((q) => q.completed_total),
    1
  );

  // Overall progress
  const overallProgress = stats.total_files_discovered > 0
    ? Math.round((totalCompleted / stats.total_files_discovered) * 100)
    : 0;

  return (
    <div className="p-6 max-w-[960px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Processing Pipeline</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {stats.status === "processing" ? (
              <span className="flex items-center gap-2">
                <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                Processing for {formatUptime(stats.uptime_seconds)}
              </span>
            ) : stats.status === "done" ? (
              <span className="flex items-center gap-2 text-green-600">
                <Check className="w-3.5 h-3.5" />
                Completed in {formatUptime(stats.uptime_seconds)}
              </span>
            ) : (
              <span className="flex items-center gap-2 text-gray-400">
                <span className="w-2 h-2 bg-gray-300 rounded-full" />
                Idle
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <button
            onClick={handleRescan}
            disabled={isTriggering}
            className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 hover:bg-gray-200 disabled:opacity-50 rounded-lg transition-colors text-gray-700"
          >
            <RotateCcw className={`w-4 h-4 ${isTriggering ? "animate-spin" : ""}`} />
            Rescan
          </button>
          <button
            onClick={handleRebuildIndex}
            disabled={isTriggering}
            className="flex items-center gap-2 px-3 py-1.5 bg-red-50 hover:bg-red-100 text-red-700 disabled:opacity-50 rounded-lg transition-colors"
          >
            <Trash2 className="w-4 h-4" />
            Rebuild
          </button>
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-red-400"}`} />
            <span className="text-xs text-gray-400">{connected ? "Live" : "Offline"}</span>
          </div>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        <div className="bg-white border border-gray-200 rounded-xl p-3.5">
          <div className="text-xs text-gray-500 mb-0.5">Discovered</div>
          <div className="text-2xl font-bold text-gray-900 tabular-nums">
            {formatNumber(stats.total_files_discovered)}
          </div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-3.5">
          <div className="text-xs text-gray-500 mb-0.5">In Progress</div>
          <div className="text-2xl font-bold text-blue-600 tabular-nums">
            {formatNumber(totalInProgress)}
          </div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-3.5">
          <div className="text-xs text-gray-500 mb-0.5">Completed</div>
          <div className="text-2xl font-bold text-green-600 tabular-nums">
            {formatNumber(totalCompleted)}
          </div>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-3.5">
          <div className="text-xs text-gray-500 mb-0.5">Overall</div>
          <div className="text-2xl font-bold text-gray-900 tabular-nums">
            {overallProgress}%
          </div>
          {stats.total_files_discovered > 0 && (
            <div className="mt-1.5 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-green-500 rounded-full transition-all duration-700"
                style={{ width: `${overallProgress}%` }}
              />
            </div>
          )}
        </div>
      </div>

      {/* Stage Details Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
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
              const barRef = stats.total_files_discovered > 0 ? stats.total_files_discovered : maxCompleted;
              const pct = barRef > 0 ? Math.min(100, Math.round((queue.completed_total / barRef) * 100)) : 0;
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
                    {formatNumber(queue.completed_total)}
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

      {/* Footer info */}
      {totalFailed > 0 && (
        <div className="mt-4 p-3 bg-red-50 border border-red-100 rounded-xl flex items-center gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>
            {totalFailed} file{totalFailed !== 1 ? "s" : ""} failed processing across all stages
          </span>
        </div>
      )}
    </div>
  );
}
