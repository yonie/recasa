import { useCallback, useEffect, useRef, useState } from "react";
import { api, type TrailParams, type TrailStop } from "../../api/client";

function trailParams(from: string, to: string): TrailParams {
  const params: TrailParams = {};
  if (from) params.date_from = from;
  if (to) params.date_to = to;
  return params;
}

/**
 * Hero Trail playback: the trail of dated, geotagged stops, the current stop,
 * auto-advance at the chosen speed, and the date range that filters it.
 */
export function useHeroTrail() {
  const [playMode, setPlayMode] = useState(false);
  const [trail, setTrail] = useState<TrailStop[]>([]);
  const [loading, setLoading] = useState(false);
  const [currentStop, setCurrentStop] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(3000); // ms per stop
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** Fetch the trail for a range; an empty result leaves the current trail alone. */
  const load = useCallback(async (from: string, to: string) => {
    setLoading(true);
    try {
      const data = await api.getTrail(trailParams(from, to));
      return data.length ? data : null;
    } catch {
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const enter = useCallback(async () => {
    const data = await load(dateFrom, dateTo);
    if (!data) return;
    setTrail(data);
    // An open range starts out as the trail's own first and last day.
    if (!dateFrom) setDateFrom(data[0]!.date);
    if (!dateTo) setDateTo(data[data.length - 1]!.date);
    setCurrentStop(0);
    setPlayMode(true);
  }, [load, dateFrom, dateTo]);

  const reload = useCallback(
    async (from: string, to: string) => {
      setPlaying(false);
      const data = await load(from, to);
      if (!data) return;
      setTrail(data);
      setCurrentStop(0);
    },
    [load]
  );

  // Moving one end past the other drags the other end along.
  const changeDateFrom = useCallback(
    (from: string) => {
      let to = dateTo;
      if (from && to && to < from) {
        to = from;
        setDateTo(to);
      }
      setDateFrom(from);
      if (playMode) void reload(from, to);
    },
    [dateTo, playMode, reload]
  );

  const changeDateTo = useCallback(
    (to: string) => {
      let from = dateFrom;
      if (to && from && from > to) {
        from = to;
        setDateFrom(from);
      }
      setDateTo(to);
      if (playMode) void reload(from, to);
    },
    [dateFrom, playMode, reload]
  );

  const exit = useCallback(() => {
    setPlayMode(false);
    setPlaying(false);
    setTrail([]);
    setCurrentStop(0);
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  // Auto-advance when playing; stop at the last stop.
  useEffect(() => {
    if (!playing || !playMode) return;
    timerRef.current = setTimeout(() => {
      setCurrentStop((prev) => {
        if (prev >= trail.length - 1) {
          setPlaying(false);
          return prev;
        }
        return prev + 1;
      });
    }, speed);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [playing, playMode, currentStop, speed, trail.length]);

  return {
    playMode,
    trail,
    loading,
    currentStop,
    setCurrentStop,
    playing,
    setPlaying,
    speed,
    setSpeed,
    dateFrom,
    dateTo,
    changeDateFrom,
    changeDateTo,
    enter,
    exit,
  };
}

export type HeroTrail = ReturnType<typeof useHeroTrail>;
