import { ChevronDown, ChevronRight } from "lucide-react";
import { clsx } from "clsx";
import type { ProcessingStats } from "../../api/client";

const fmt = (n: number) => n.toLocaleString();

/** Photos still waiting on some enabled stage, not counting terminal failures. */
function pendingCount(stats: ProcessingStats): number {
  let max = 0;
  for (const stage of Object.values(stats.stages)) {
    if (stage && stage.enabled && stage.total > 1) {
      max = Math.max(max, stage.total - stage.completed - stage.failed);
    }
  }
  return max;
}

interface SummaryCardsProps {
  processingStats: ProcessingStats | undefined;
  unreadableCount: number;
  showFailures: boolean;
  onToggleFailures: () => void;
}

export function SummaryCards({ processingStats, unreadableCount, showFailures, onToggleFailures }: SummaryCardsProps) {
  const pending = processingStats ? pendingCount(processingStats) : 0;
  const videos = processingStats?.total_videos ?? 0;

  return (
    <div className="grid grid-cols-3 gap-3 mb-6">
      <div className="bg-white border border-gray-200 rounded-xl p-3.5">
        <div className="text-xs text-gray-500 mb-0.5">Indexed Photos</div>
        {processingStats ? (
          <div className="text-2xl font-bold text-gray-900 tabular-nums">
            {fmt(processingStats.total_photos || 0)}
          </div>
        ) : (
          <div className="h-8 w-20 bg-gray-100 rounded animate-pulse" />
        )}
        {videos > 0 && (
          <div className="text-xs text-gray-400 mt-0.5">
            + {fmt(videos)} video
            {videos !== 1 ? "s" : ""}
          </div>
        )}
      </div>
      <div
        className={clsx(
          "border rounded-xl p-3.5",
          pending > 0 ? "bg-white border-blue-200" : "bg-gray-50/60 border-gray-200"
        )}
      >
        <div className="text-xs text-gray-500 mb-0.5">Pending</div>
        {processingStats ? (
          <div className={clsx("text-2xl font-bold tabular-nums", pending > 0 ? "text-blue-600" : "text-gray-300")}>
            {fmt(pending)}
          </div>
        ) : (
          <div className="h-8 w-14 bg-gray-100 rounded animate-pulse" />
        )}
      </div>
      <button
        onClick={onToggleFailures}
        disabled={unreadableCount === 0}
        className={clsx(
          "border rounded-xl p-3.5 text-left transition-colors",
          unreadableCount > 0
            ? "bg-amber-50 border-amber-200 hover:bg-amber-100 cursor-pointer"
            : "bg-gray-50/60 border-gray-200"
        )}
      >
        <div
          className={clsx(
            "text-xs mb-0.5 flex items-center gap-1",
            unreadableCount > 0 ? "text-amber-700" : "text-gray-500"
          )}
        >
          Unreadable
          {unreadableCount > 0 &&
            (showFailures ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />)}
        </div>
        <div
          className={clsx(
            "text-2xl font-bold tabular-nums",
            unreadableCount > 0 ? "text-amber-600" : "text-gray-300"
          )}
        >
          {fmt(unreadableCount)}
        </div>
      </button>
    </div>
  );
}
