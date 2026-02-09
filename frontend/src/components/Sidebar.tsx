import { NavLink } from "react-router-dom";
import {
  ImageIcon,
  FolderTree,
  Calendar,
  Star,
  Copy,
  HardDrive,
  Camera,
  Users,
  Tag,
  CalendarDays,
  Map,
  Activity,
} from "lucide-react";
import { clsx } from "clsx";
import { useStore } from "../store/useStore";

const navItems = [
  { to: "/", icon: ImageIcon, label: "Photos" },
  { to: "/folders", icon: FolderTree, label: "Folders" },
  { to: "/years", icon: Calendar, label: "Years" },
  { to: "/favorites", icon: Star, label: "Favorites" },
  { to: "/people", icon: Users, label: "People" },
  { to: "/tags", icon: Tag, label: "Tags" },
  { to: "/events", icon: CalendarDays, label: "Events" },
  { to: "/locations", icon: Map, label: "Locations" },
  { to: "/duplicates", icon: Copy, label: "Duplicates" },
  { to: "/large-files", icon: HardDrive, label: "Large Files" },
  { to: "/pipeline", icon: Activity, label: "Pipeline" },
];

export function Sidebar() {
  const stats = useStore((s) => s.stats);

  return (
    <aside className="w-64 border-r border-gray-200 bg-gray-50 flex flex-col h-full">
      {/* Logo */}
      <div className="flex items-center gap-2 px-5 py-4 border-b border-gray-200">
        <Camera className="w-7 h-7 text-primary-600" />
        <h1 className="text-xl font-bold text-gray-900">Recasa</h1>
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
          {stats.total_tags > 0 && (
            <div className="flex justify-between">
              <span>Tags</span>
              <span className="font-medium text-gray-700">
                {stats.total_tags.toLocaleString()}
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
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}
