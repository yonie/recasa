import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";

/**
 * Library totals for the sidebar. Being a query, any blanket invalidation after
 * a favorite/flag/print toggle refreshes it too, so the counts follow the
 * action instead of waiting for the next poll.
 */
export function useLibraryStats() {
  return useQuery({
    queryKey: queryKeys.stats,
    queryFn: api.getStats,
    refetchInterval: 30_000,
  }).data;
}

/**
 * Pipeline state, polled every 3s. The sidebar and the pipeline page share
 * this one query, and the pipeline page's websocket writes into it, so both
 * stay in step without polling twice.
 */
export function usePipelineStatus() {
  return useQuery({
    queryKey: queryKeys.pipelineStatus,
    queryFn: api.getPipelineStatus,
    refetchInterval: 3000,
  }).data;
}
