import { Activity } from "lucide-react";
import { STAGES, type ProcessingStats, type StageName, type StageStats } from "../../api/client";
import { STAGE_ICONS, STAGE_LABELS } from "./stages";

const fmt = (n: number) => n.toLocaleString();

const EMPTY_STAGE: StageStats = {
  status: "pending",
  queued: 0,
  completed: 0,
  total: 0,
  enabled: true,
  failed: 0,
};

/** One row per stage: status, done/total, failures and a progress bar. */
export function StageTable({ processingStats }: { processingStats: ProcessingStats | undefined }) {
  return (
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
          {STAGES.map((name) =>
            processingStats ? (
              <StageRow key={name} name={name} stage={processingStats.stages[name] ?? EMPTY_STAGE} />
            ) : (
              <SkeletonRow key={name} name={name} />
            )
          )}
        </tbody>
      </table>
    </div>
  );
}

function StageCell({ name, children }: { name: StageName; children?: React.ReactNode }) {
  const Icon = STAGE_ICONS[name];
  return (
    <td className="px-3 py-2">
      <div className="flex items-center gap-2">
        <Icon className="w-3.5 h-3.5 text-gray-400 shrink-0" />
        <span className="font-medium text-gray-900">{STAGE_LABELS[name]}</span>
        {children}
      </div>
    </td>
  );
}

function SkeletonRow({ name }: { name: StageName }) {
  return (
    <tr className="border-b border-gray-50 last:border-0">
      <StageCell name={name} />
      <td className="px-3 py-2">
        <div className="h-4 w-16 bg-gray-100 rounded-full animate-pulse" />
      </td>
      <td className="px-3 py-2">
        <div className="h-4 w-20 bg-gray-100 rounded animate-pulse ml-auto" />
      </td>
      <td className="px-3 py-2">
        <div className="h-4 w-6 bg-gray-100 rounded animate-pulse ml-auto" />
      </td>
      <td className="px-3 py-2">
        <div className="h-1.5 bg-gray-100 rounded-full animate-pulse" />
      </td>
    </tr>
  );
}

function Badge({ className, children }: { className: string; children: React.ReactNode }) {
  return <span className={`inline-flex text-[10px] font-medium px-1.5 py-0.5 rounded-full ${className}`}>{children}</span>;
}

function StageRow({ name, stage }: { name: StageName; stage: StageStats }) {
  // Event detection is a batch over the whole library, not a per-photo stage.
  const isBatch = name === "events";
  const donePct = stage.total > 0 ? Math.floor((stage.completed / stage.total) * 100) : 0;
  const failedPct = stage.total > 0 ? Math.ceil((stage.failed / stage.total) * 100) : 0;
  const complete = stage.completed + stage.failed >= stage.total && stage.total > 0;

  return (
    <tr className="border-b border-gray-50 last:border-0 hover:bg-gray-50/40">
      <StageCell name={name}>
        {stage.faces_found !== undefined && stage.faces_found > 0 && (
          <span className="text-[10px] text-gray-400">({fmt(stage.faces_found)} faces)</span>
        )}
      </StageCell>
      <td className="px-3 py-2">
        {!stage.enabled ? (
          <Badge className="text-gray-500 bg-gray-100">Disabled</Badge>
        ) : stage.queued > 0 ? (
          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded-full">
            <Activity className="w-2.5 h-2.5 animate-pulse" />
            Processing ({fmt(stage.queued)} queued)
          </span>
        ) : stage.failed > 0 ? (
          <Badge className="text-amber-700 bg-amber-50">Done with exceptions</Badge>
        ) : complete || isBatch ? (
          <Badge className="text-green-600 bg-green-50">Done</Badge>
        ) : (
          <Badge className="text-gray-500 bg-gray-100">Waiting</Badge>
        )}
      </td>
      <td className="px-3 py-2 text-right tabular-nums font-medium text-gray-900">
        {isBatch ? (
          <span className="text-gray-500">{fmt(stage.count || 0)} events</span>
        ) : (
          <>
            {fmt(stage.completed)}
            <span className="text-gray-400"> / {fmt(stage.total)}</span>
          </>
        )}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {stage.failed > 0 ? (
          <span className="font-medium text-amber-600">{fmt(stage.failed)}</span>
        ) : (
          <span className="text-gray-200">-</span>
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
                  <div className="h-full bg-amber-400" style={{ width: `max(${failedPct}%, 6px)` }} />
                )}
              </>
            ) : null}
          </div>
          <span className="text-[10px] tabular-nums text-gray-500 w-8 text-right">
            {isBatch ? "" : !stage.enabled ? "off" : complete && stage.failed === 0 ? "100%" : `${donePct}%`}
          </span>
        </div>
      </td>
    </tr>
  );
}
