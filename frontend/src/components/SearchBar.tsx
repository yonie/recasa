import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Search, X } from "lucide-react";
import { useStore } from "../store/useStore";
import { ScanProgress } from "./ScanProgress";

export function SearchBar() {
  const navigate = useNavigate();
  const { searchQuery, setSearchQuery } = useStore();
  const [inputValue, setInputValue] = useState(searchQuery);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const q = inputValue.trim();
      setSearchQuery(q);
      if (q) {
        navigate(`/search?q=${encodeURIComponent(q)}`);
      }
    },
    [inputValue, navigate, setSearchQuery]
  );

  const handleClear = useCallback(() => {
    setInputValue("");
    setSearchQuery("");
  }, [setSearchQuery]);

  return (
    <header className="h-14 border-b border-gray-200 bg-white flex items-center px-4 gap-4">
      <form onSubmit={handleSubmit} className="flex-1 max-w-2xl relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
        <input
          type="text"
          placeholder="Search photos by name, location, tag..."
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          className="w-full pl-9 pr-8 py-2 bg-gray-100 rounded-lg text-sm
                     border border-transparent
                     focus:bg-white focus:border-primary-300 focus:ring-2 focus:ring-primary-100
                     outline-none transition-all"
        />
        {inputValue && (
          <button
            type="button"
            onClick={handleClear}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-gray-200 rounded"
          >
            <X className="w-3.5 h-3.5 text-gray-500" />
          </button>
        )}
      </form>

      <ScanProgress />
    </header>
  );
}
