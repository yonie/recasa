import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { api } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import { usePipelineStatus } from "../../hooks/useServerState";
import { FailuresDrawer } from "./FailuresDrawer";
import { REBUILDABLE } from "./stages";
import { StageTable } from "./StageTable";
import { StatusHero } from "./StatusHero";
import { SummaryCards } from "./SummaryCards";
import { usePipelineSocket } from "./usePipelineSocket";

export function Pipeline() {
  const [isTriggering, setIsTriggering] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [showFailures, setShowFailures] = useState(false);

  // Each query renders as soon as its own data arrives (no combined await),
  // and react-query's cache makes revisits instant with a background refresh.
  const stats = usePipelineStatus();
  const { data: processingStats } = useQuery({
    queryKey: queryKeys.processingStats,
    queryFn: api.getProcessingStats,
    refetchInterval: 3000,
  });
  const { data: failures = [] } = useQuery({
    queryKey: queryKeys.pipelineFailures,
    queryFn: api.getPipelineFailures,
    refetchInterval: 3000,
  });

  const wsState = usePipelineSocket((data) => {
    if (data.state === "idle") setIsStopping(false);
  });

  const isActive = stats?.state === "scanning" || stats?.state === "processing";
  const unreadableCount = new Set(failures.map((f) => f.file_hash)).size;

  const handleRescan = async () => {
    if (isTriggering) return;
    setIsTriggering(true);
    try {
      await api.triggerScan();
    } catch {
      // The status poll shows whether a scan started.
    } finally {
      setIsTriggering(false);
    }
  };

  const handleStop = async () => {
    setIsStopping(true);
    try {
      await api.stopPipeline();
    } catch {
      // Stays "Stopping…" until the status says idle, as before.
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
      // The stage table shows what actually happened.
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
      // As above: the status shows the outcome.
    } finally {
      setIsTriggering(false);
    }
  };

  return (
    <div className="p-6 max-w-[960px] mx-auto overflow-y-auto h-full">
      {/* Live-updates notice: only when a previously-open connection dropped */}
      {wsState === "lost" && (
        <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 flex items-center gap-2 text-sm text-amber-700">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          Live updates interrupted — reconnecting automatically. Shown status may lag a few seconds.
        </div>
      )}

      <StatusHero
        stats={stats}
        isActive={isActive}
        isTriggering={isTriggering}
        isStopping={isStopping}
        onRescan={handleRescan}
        onStop={handleStop}
      />

      <SummaryCards
        processingStats={processingStats}
        unreadableCount={unreadableCount}
        showFailures={showFailures}
        onToggleFailures={() => setShowFailures((s) => !s)}
      />

      {showFailures && failures.length > 0 && <FailuresDrawer failures={failures} />}

      <StageTable processingStats={processingStats} />

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
              disabled={isActive || !stats}
              className="px-3 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-100 disabled:opacity-40 transition-colors"
            >
              {label}
            </button>
          ))}
        </div>
        <button
          onClick={handleClearIndex}
          disabled={isActive || isTriggering || !stats}
          className="text-xs text-red-600 hover:text-red-700 hover:underline disabled:opacity-40"
        >
          Delete entire index and start over…
        </button>
      </div>
    </div>
  );
}
