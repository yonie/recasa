import { useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  ImageIcon,
  Clapperboard,
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
  Printer,
  Flag,
  Activity,
  ArrowDownUp,
  Wrench,
  ChevronDown,
  ChevronRight,
  X,
  Loader2,
} from "lucide-react";
import { clsx } from "clsx";
import type { LibraryStats } from "../api/client";
import { useLibraryStats, usePipelineStatus } from "../hooks/useServerState";
import { formatBytes } from "../lib/format";
import { useStore } from "../store/useStore";

const navItems = [
  { to: "/", icon: ImageIcon, label: "Photos" },
  { to: "/videos", icon: Clapperboard, label: "Videos" },
  { to: "/folders", icon: FolderTree, label: "Folders" },
  { to: "/years", icon: Calendar, label: "Years" },
  { to: "/favorites", icon: Star, label: "Favorites" },
  { to: "/to-print", icon: Printer, label: "To Print" },
  { to: "/people", icon: Users, label: "People" },
  { to: "/events", icon: CalendarDays, label: "Events" },
  { to: "/locations", icon: Map, label: "Locations" },
  { to: "/tags", icon: Tag, label: "Tags" },
];

const toolItems = [
  { to: "/flagged", icon: Flag, label: "Flagged" },
  { to: "/duplicates", icon: Copy, label: "Duplicates" },
  { to: "/large-files", icon: HardDrive, label: "Large Files" },
  { to: "/export-import", icon: ArrowDownUp, label: "Export / Import" },
];

export function Sidebar() {
  const stats = useLibraryStats();
  const pipelineStats = usePipelineStatus();
  const sidebarOpen = useStore((s) => s.sidebarOpen);
  const closeSidebar = useStore((s) => s.closeSidebar);
  const location = useLocation();
  const navigate = useNavigate();
  const isToolRoute = toolItems.some((item) => location.pathname.startsWith(item.to));
  const [toolsOpen, setToolsOpen] = useState(isToolRoute);
  // Landing on a tool page opens the submenu it lives in, and it stays open.
  if (isToolRoute && !toolsOpen) setToolsOpen(true);

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
          <button
            onClick={() => {
              closeSidebar();
              navigate("/");
            }}
            className="flex items-center gap-2 hover:opacity-80 transition-opacity">
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

        {/* Navigation. On a phone the drawer covers the page, so following a link closes it. */}
        <nav className="flex-1 overflow-y-auto py-3 px-3">
          <div className="space-y-0.5">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                onClick={closeSidebar}
                className={({ isActive }) =>
                  clsx("sidebar-link", isActive && "active")
                }
              >
                <item.icon className="w-5 h-5 flex-shrink-0" />
                <span>{item.label}</span>
                {item.to === "/to-print" && (stats?.to_print_count ?? 0) > 0 && (
                  <span className="ml-auto text-xs font-medium bg-primary-100 text-primary-700 px-2 py-0.5 rounded-full">
                    {stats?.to_print_count}
                  </span>
                )}
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
                    onClick={closeSidebar}
                    className={({ isActive }) =>
                      clsx("sidebar-link", isActive && "active")
                    }
                  >
                    <item.icon className="w-5 h-5 flex-shrink-0" />
                    <span>{item.label}</span>
                    {item.to === "/flagged" && (stats?.flagged_count ?? 0) > 0 && (
                      <span className="ml-auto text-xs font-medium bg-red-100 text-red-700 px-2 py-0.5 rounded-full">
                        {stats?.flagged_count}
                      </span>
                    )}
                  </NavLink>
                ))}
              </div>
            )}

            <NavLink
              to="/pipeline"
              onClick={closeSidebar}
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

        {stats && <StatsFooter stats={stats} />}
      </aside>
    </>
  );
}

function StatsFooter({ stats }: { stats: LibraryStats }) {
  // Optional rows only show once there is something to count.
  const rows: [string, string, boolean][] = [
    ["Photos", stats.total_photos.toLocaleString(), true],
    ["Videos", stats.videos_count.toLocaleString(), stats.videos_count > 0],
    ["Size", formatBytes(stats.total_size_bytes), true],
    ["People", stats.total_persons.toLocaleString(), stats.total_persons > 0],
    ["Locations", stats.locations_count.toLocaleString(), stats.locations_count > 0],
    ["Favorites", stats.favorites_count.toLocaleString(), stats.favorites_count > 0],
  ];
  return (
    <div className="px-5 py-3 border-t border-gray-200 text-xs text-gray-500 space-y-1">
      {rows
        .filter(([, , show]) => show)
        .map(([label, value]) => (
          <div key={label} className="flex justify-between">
            <span>{label}</span>
            <span className="font-medium text-gray-700">{value}</span>
          </div>
        ))}
    </div>
  );
}
