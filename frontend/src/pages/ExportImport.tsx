import { useState, useRef } from "react";
import { Download, Upload, Loader2, CheckCircle, AlertCircle } from "lucide-react";

export function ExportImport() {
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleExport = async () => {
    setExporting(true);
    setResult(null);
    try {
      const res = await fetch("/api/user-data/export");
      if (!res.ok) throw new Error("Export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "recasa-user-data.json";
      a.click();
      URL.revokeObjectURL(url);
      setResult({ type: "success", message: "Export downloaded" });
    } catch {
      setResult({ type: "error", message: "Export failed" });
    } finally {
      setExporting(false);
    }
  };

  const handleImport = async (file: File) => {
    setImporting(true);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/user-data/import", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (data.status === "error") {
        setResult({ type: "error", message: data.message });
      } else {
        const parts: string[] = [];
        if (data.favorites_restored > 0)
          parts.push(`${data.favorites_restored} favorites restored`);
        if (data.persons_restored > 0)
          parts.push(`${data.persons_restored} people restored`);
        if (data.persons_pending > 0)
          parts.push(
            `${data.persons_pending} people will be restored after face detection completes`
          );
        setResult({
          type: "success",
          message: parts.length > 0 ? parts.join(". ") : "Nothing to restore",
        });
      }
    } catch {
      setResult({ type: "error", message: "Import failed" });
    } finally {
      setImporting(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div className="overflow-y-auto h-full">
      <div className="px-4 py-3 border-b border-gray-100">
        <h1 className="text-lg font-semibold">Export / Import</h1>
      </div>

      <div className="p-6 max-w-xl space-y-8">
        <p className="text-sm text-gray-500">
          Export your favorites and named people to a JSON file. Use import to
          restore them after rebuilding the index.
        </p>

        {/* Export */}
        <section className="space-y-3">
          <h2 className="text-base font-semibold text-gray-700">Export</h2>
          <p className="text-sm text-gray-400">
            Downloads a file containing your favorited photos and all named /
            ignored people with their face signatures.
          </p>
          <button
            onClick={handleExport}
            disabled={exporting}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors"
          >
            {exporting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Download className="w-4 h-4" />
            )}
            {exporting ? "Exporting..." : "Export data"}
          </button>
        </section>

        {/* Import */}
        <section className="space-y-3">
          <h2 className="text-base font-semibold text-gray-700">Import</h2>
          <p className="text-sm text-gray-400">
            Restore favorites and person names from a previous export. For best
            results, import after face detection and clustering have completed.
          </p>
          <label
            className={`flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg cursor-pointer hover:bg-gray-50 transition-colors w-fit ${
              importing ? "opacity-50 pointer-events-none" : ""
            }`}
          >
            {importing ? (
              <Loader2 className="w-4 h-4 animate-spin text-gray-500" />
            ) : (
              <Upload className="w-4 h-4 text-gray-500" />
            )}
            <span className="text-sm text-gray-700">
              {importing ? "Importing..." : "Choose file to import"}
            </span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json"
              className="hidden"
              disabled={importing}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleImport(file);
              }}
            />
          </label>
        </section>

        {/* Result */}
        {result && (
          <div
            className={`flex items-start gap-3 p-4 rounded-lg ${
              result.type === "success"
                ? "bg-green-50 text-green-700"
                : "bg-red-50 text-red-700"
            }`}
          >
            {result.type === "success" ? (
              <CheckCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            ) : (
              <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
            )}
            <p className="text-sm">{result.message}</p>
          </div>
        )}
      </div>
    </div>
  );
}
