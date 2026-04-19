import { useState, useEffect } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  ImageIcon,
  FolderTree,
  Calendar,
  Star,
  Copy,
  HardDrive,
  Camera,
  Users,
  CalendarDays,
  Map,
  Tag,
  Activity,
  ArrowDownUp,
  Wrench,
  ChevronDown,
  ChevronRight,
  X,
  Loader2,
} from "lucide-react";
import { clsx } from "clsx";
import { useStore } from "../store/useStore";
import { type PipelineStats } from "../api/client";

const navItems = [
  { to: "/", icon: ImageIcon, label: "Photos" },
  { to: "/folders", icon: FolderTree, label: "Folders" },
  { to: "/years", icon: Calendar, label: "Years" },
  { to: "/favorites", icon: Star, label: "Favorites" },
  { to: "/people", icon: Users, label: "People" },
  { to: "/events", icon: CalendarDays, label: "Events" },
  { to: "/locations", icon: Map, label: "Locations" },
  { to: "/tags", icon: Tag, label: "Tags" },
];

const toolItems = [
  { to: "/duplicates", icon: Copy, label: "Duplicates" },
  { to: "/large-files", icon: HardDrive, label: "Large Files" },
  { to: "/export-import", icon: ArrowDownUp, label: "Export / Import" },
];

export function Sidebar() {
  const stats = useStore((s) => s.stats);
  const sidebarOpen = useStore((s) => s.sidebarOpen);
  const closeSidebar = useStore((s) => s.closeSidebar);
  const location = useLocation();
  const navigate = useNavigate();
  const isToolRoute = toolItems.some((item) => location.pathname.startsWith(item.to));
  const [toolsOpen, setToolsOpen] = useState(isToolRoute);
  const [pipelineStats, setPipelineStats] = useState<PipelineStats | null>(null);

  useEffect(() => {
    if (isToolRoute && !toolsOpen) setToolsOpen(true);
  }, [isToolRoute, toolsOpen]);

  useEffect(() => {
    async function fetchPipelineStatus() {
      try {
        const res = await fetch("/api/pipeline/status");
        const data = await res.json();
        setPipelineStats(data);
      } catch {
        // ignore
      }
    }
    fetchPipelineStatus();
    const interval = setInterval(fetchPipelineStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  const pipelineActive = pipelineStats?.state === "scanning" || pipelineStats?.state === "processing";

  return (
    <>
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={closeSidebar}
        />
      )}

      {/* Sidebar */}
      <aside
        className={clsx(
          "fixed lg:relative inset-y-0 left-0 z-50 lg:z-auto",
          "w-64 border-r border-gray-200 bg-gray-50 flex flex-col h-full",
          "transform transition-transform duration-300 lg:transform-none",
          sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
          "pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]"
        )}
      >
        {/* Logo */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <button onClick={() => navigate("/")} className="flex items-center gap-2 hover:opacity-80 transition-opacity">
            <Camera className="w-7 h-7 text-primary-600" />
            <h1 className="text-xl font-bold text-gray-900">Recasa</h1>
          </button>
          <button
            onClick={closeSidebar}
            className="lg:hidden p-1 hover:bg-gray-200 rounded"
          >
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-3 px-3">
          <div className="space-y-0.5">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  clsx("sidebar-link", isActive && "active")
                }
              >
                <item.icon className="w-5 h-5 flex-shrink-0" />
                <span>{item.label}</span>
              </NavLink>
            ))}

            {/* Tools submenu */}
            <button
              onClick={() => setToolsOpen(!toolsOpen)}
              className="sidebar-link w-full"
            >
              <Wrench className="w-5 h-5 flex-shrink-0" />
              <span className="flex-1 text-left">Tools</span>
              {toolsOpen ? (
                <ChevronDown className="w-4 h-4 text-gray-400" />
              ) : (
                <ChevronRight className="w-4 h-4 text-gray-400" />
              )}
            </button>
            {toolsOpen && (
              <div className="ml-3 space-y-0.5">
                {toolItems.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      clsx("sidebar-link", isActive && "active")
                    }
                  >
                    <item.icon className="w-5 h-5 flex-shrink-0" />
                    <span>{item.label}</span>
                  </NavLink>
                ))}
              </div>
            )}

            <NavLink
              to="/pipeline"
              className={({ isActive }) =>
                clsx("sidebar-link", isActive && "active")
              }
            >
              {pipelineActive ? (
                <Loader2 className="w-5 h-5 flex-shrink-0 animate-spin text-blue-500" />
              ) : (
                <Activity className="w-5 h-5 flex-shrink-0" />
              )}
              <span>Pipeline</span>
              {pipelineActive && (
                <span className="ml-auto text-[10px] text-blue-500 font-medium">running</span>
              )}
            </NavLink>
          </div>
        </nav>

        {/* Stats footer */}
        {stats && (
          <div className="px-5 py-3 border-t border-gray-200 text-xs text-gray-500 space-y-1">
            <div className="flex justify-between">
              <span>Photos</span>
              <span className="font-medium text-gray-700">
                {stats.total_photos.toLocaleString()}
              </span>
            </div>
            <div className="flex justify-between">
              <span>Size</span>
              <span className="font-medium text-gray-700">
                {formatBytes(stats.total_size_bytes)}
              </span>
            </div>
            {stats.total_persons > 0 && (
              <div className="flex justify-between">
                <span>People</span>
                <span className="font-medium text-gray-700">
                  {stats.total_persons.toLocaleString()}
                </span>
              </div>
            )}
            {stats.locations_count > 0 && (
              <div className="flex justify-between">
                <span>Locations</span>
                <span className="font-medium text-gray-700">
                  {stats.locations_count.toLocaleString()}
                </span>
              </div>
            )}
            {stats.favorites_count > 0 && (
              <div className="flex justify-between">
                <span>Favorites</span>
                <span className="font-medium text-gray-700">
                  {stats.favorites_count.toLocaleString()}
                </span>
              </div>
            )}
          </div>
        )}
      </aside>
    </>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}
