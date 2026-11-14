import { Crop, Expand, Grid2x2, Grid3x3, LayoutGrid } from "lucide-react";
import { useStore, type GridSize } from "../store/useStore";

const GRID_CYCLE: GridSize[] = ["S", "M", "L"];
const GRID_ICON = { S: LayoutGrid, M: Grid3x3, L: Grid2x2 } as const;

const BUTTON =
  "w-10 h-10 rounded-full bg-white/95 shadow-lg border border-gray-200 " +
  "flex items-center justify-center hover:bg-gray-100 transition-colors";

function GridSizeToggle() {
  const gridSize = useStore((s) => s.gridSize);
  const setGridSize = useStore((s) => s.setGridSize);
  const Icon = GRID_ICON[gridSize];
  const next = GRID_CYCLE[(GRID_CYCLE.indexOf(gridSize) + 1) % GRID_CYCLE.length]!;

  return (
    <button onClick={() => setGridSize(next)} className={BUTTON} title={`Grid size: ${gridSize}`}>
      <Icon className="w-5 h-5 text-gray-600" />
    </button>
  );
}

function GridFitToggle() {
  const gridFit = useStore((s) => s.gridFit);
  const setGridFit = useStore((s) => s.setGridFit);
  const square = gridFit === "square";

  return (
    <button
      onClick={() => setGridFit(square ? "full" : "square")}
      className={BUTTON}
      title={
        square
          ? "Showing cropped squares — click for full photos"
          : "Showing full photos — click for cropped squares"
      }
    >
      {square ? (
        <Crop className="w-5 h-5 text-gray-600" />
      ) : (
        <Expand className="w-5 h-5 text-gray-600" />
      )}
    </button>
  );
}

/** Floating grid display controls (size + square/full fit), shared by all grid pages. */
export function GridViewControls() {
  return (
    <div className="fixed bottom-4 right-4 z-30 flex flex-col gap-2">
      <GridFitToggle />
      <GridSizeToggle />
    </div>
  );
}
