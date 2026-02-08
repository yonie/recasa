import { useEffect, useState, useCallback } from "react";
import { Folder, ChevronRight, ChevronDown } from "lucide-react";
import { clsx } from "clsx";
import { api, type DirectoryNode, type PhotoSummary } from "../api/client";
import { PhotoGrid } from "../components/PhotoGrid";
import { useStore } from "../store/useStore";
import { Loader2 } from "lucide-react";

export function Folders() {
  const [tree, setTree] = useState<DirectoryNode[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [photos, setPhotos] = useState<PhotoSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [photosLoading, setPhotosLoading] = useState(false);
  const openViewer = useStore((s) => s.openViewer);

  useEffect(() => {
    async function load() {
      try {
        const data = await api.getDirectoryTree();
        setTree(data);
      } catch {
        // ignore
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const handleSelectFolder = useCallback(async (path: string) => {
    setSelectedPath(path);
    setPhotosLoading(true);
    try {
      const data = await api.getDirectoryPhotos(path, { page_size: 200 });
      setPhotos(data.items);
    } catch {
      setPhotos([]);
    } finally {
      setPhotosLoading(false);
    }
  }, []);

  const handlePhotoClick = useCallback(
    async (photo: PhotoSummary, index: number) => {
      try {
        const detail = await api.getPhoto(photo.file_hash);
        openViewer(detail, photos, index);
      } catch {
        // ignore
      }
    },
    [openViewer, photos]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

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
        {!selectedPath ? (
          <div className="flex items-center justify-center h-64 text-gray-400">
            <p>Select a folder to browse photos</p>
          </div>
        ) : photosLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="w-8 h-8 animate-spin text-primary-500" />
          </div>
        ) : (
          <>
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="text-sm font-medium text-gray-600">{selectedPath}</h2>
            </div>
            <PhotoGrid photos={photos} onPhotoClick={handlePhotoClick} />
          </>
        )}
      </div>
    </div>
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
        hasChildren &&
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
