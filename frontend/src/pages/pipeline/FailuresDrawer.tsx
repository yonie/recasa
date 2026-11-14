import { Eye } from "lucide-react";
import type { StageFailureItem } from "../../api/client";
import { stageLabel } from "./stages";

/** Files a stage gave up on, with the stage and the error. */
export function FailuresDrawer({ failures }: { failures: StageFailureItem[] }) {
  return (
    <div className="bg-white border border-amber-200 rounded-xl overflow-hidden mb-6">
      <div className="px-3 py-2 bg-amber-50 border-b border-amber-100 flex items-center gap-2">
        <Eye className="w-4 h-4 text-amber-600" />
        <span className="text-sm font-medium text-amber-800">Files that could not be processed</span>
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
                    {stageLabel(f.stage)}
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
  );
}
