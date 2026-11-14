import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Folder } from "lucide-react";
import { clsx } from "clsx";
import { api, encodePath, type DirectoryNode } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { ErrorState, PageSpinner } from "../components/Page";
import { PhotoGrid } from "../components/PhotoGrid";
import { useOpenPhoto } from "../hooks/useOpenPhoto";

export function Folders() {
  const navigate = useNavigate();
  const location = useLocation();
  // Selected folder lives in the URL (/folders/<path>) so Back and deep links work.
  const selectedPath = decodeURIComponent(location.pathname.replace(/^\/folders\/?/, "")) || null;

  const { data: tree = [], isLoading, error } = useQuery({
    queryKey: queryKeys.directoryTree,
    queryFn: api.getDirectoryTree,
  });

  const handleSelectFolder = (path: string) => navigate(`/folders/${encodePath(path)}`);

  if (isLoading) return <PageSpinner />;
  if (error) return <ErrorState error={error} />;

  return (
    <div className="flex h-full">
      {/* Folder tree sidebar */}
      <div className="w-72 border-r border-gray-200 overflow-y-auto bg-gray-50 p-2">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide px-2 py-2">
          Directories
        </h2>
        {tree.length === 0 ? (
          <p className="text-sm text-gray-400 px-2">No directories found</p>
        ) : (
          tree.map((node) => (
            <TreeNode
              key={node.path}
              node={node}
              selectedPath={selectedPath}
              onSelect={handleSelectFolder}
              depth={0}
            />
          ))
        )}
      </div>

      {/* Photo grid */}
      <div className="flex-1 overflow-y-auto">
        {selectedPath ? (
          <FolderPhotos path={selectedPath} />
        ) : (
          <div className="flex items-center justify-center h-64 text-gray-400">
            <p>Select a folder to browse photos</p>
          </div>
        )}
      </div>
    </div>
  );
}

function FolderPhotos({ path }: { path: string }) {
  const openPhoto = useOpenPhoto();
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.directoryPhotos(path),
    queryFn: () => api.getDirectoryPhotos(path, { page_size: 200 }),
  });

  if (isLoading) return <PageSpinner />;
  if (error) return <ErrorState error={error} />;
  return (
    <>
      <div className="px-4 py-3 border-b border-gray-100">
        <h2 className="text-sm font-medium text-gray-600">{path}</h2>
      </div>
      <PhotoGrid photos={data?.items ?? []} onPhotoClick={openPhoto} />
    </>
  );
}

interface TreeNodeProps {
  node: DirectoryNode;
  selectedPath: string | null;
  onSelect: (path: string) => void;
  depth: number;
}

function TreeNode({ node, selectedPath, onSelect, depth }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(depth < 1);
  const hasChildren = node.children.length > 0;
  const isSelected = selectedPath === node.path;

  return (
    <div>
      <button
        onClick={() => {
          onSelect(node.path);
          if (hasChildren) setExpanded((e) => !e);
        }}
        className={clsx(
          "w-full flex items-center gap-1.5 px-2 py-1.5 rounded text-sm",
          "hover:bg-gray-200 transition-colors text-left",
          isSelected && "bg-primary-50 text-primary-700"
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {hasChildren ? (
          expanded ? (
            <ChevronDown className="w-4 h-4 flex-shrink-0 text-gray-400" />
          ) : (
            <ChevronRight className="w-4 h-4 flex-shrink-0 text-gray-400" />
          )
        ) : (
          <span className="w-4" />
        )}
        <Folder className="w-4 h-4 flex-shrink-0 text-gray-400" />
        <span className="truncate">{node.name}</span>
        <span className="ml-auto text-xs text-gray-400">{node.photo_count}</span>
      </button>

      {expanded &&
        node.children.map((child) => (
          <TreeNode
            key={child.path}
            node={child}
            selectedPath={selectedPath}
            onSelect={onSelect}
            depth={depth + 1}
          />
        ))}
    </div>
  );
}
