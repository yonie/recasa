/**
 * Keep chosen react-query results in IndexedDB across page loads, so the
 * first screen can render from the last known data while the real request
 * runs. Opening the app used to mean a blank spinner for the 2-3 s the Pi
 * needs to build the Photos timeline; now the timeline paints at once and is
 * replaced when the fresh copy lands.
 *
 * Best effort throughout: without IndexedDB (private mode, quota) nothing is
 * restored or saved and the app behaves exactly as without this.
 */
import type { QueryClient, QueryKey } from "@tanstack/react-query";

const DB_NAME = "recasa-cache";
const STORE = "queries";
// Bump when the shape of a persisted response changes, to drop old copies.
const VERSION = 1;
// Older copies are not worth showing, even briefly.
const MAX_AGE_MS = 14 * 24 * 3600 * 1000;

interface Saved {
  version: number;
  updatedAt: number;
  data: unknown;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  dbPromise ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

const idKey = (key: QueryKey) => JSON.stringify(key);

async function read(key: QueryKey): Promise<Saved | undefined> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const req = db.transaction(STORE).objectStore(STORE).get(idKey(key));
    req.onsuccess = () => resolve(req.result as Saved | undefined);
    req.onerror = () => reject(req.error);
  });
}

async function write(key: QueryKey, saved: Saved): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(saved, idKey(key));
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/**
 * Seed the cache with the saved copy of `key`, keeping its original fetch
 * time so react-query still treats it as stale and refetches on mount.
 * Gives up after `timeoutMs`, so a slow disk never delays the first render
 * by more than that.
 */
export async function restoreQuery(queryClient: QueryClient, key: QueryKey, timeoutMs = 300) {
  try {
    const saved = await Promise.race([
      read(key),
      new Promise<undefined>((resolve) => setTimeout(() => resolve(undefined), timeoutMs)),
    ]);
    if (
      saved &&
      saved.version === VERSION &&
      Date.now() - saved.updatedAt < MAX_AGE_MS &&
      queryClient.getQueryData(key) === undefined
    ) {
      queryClient.setQueryData(key, saved.data, { updatedAt: saved.updatedAt });
    }
  } catch {
    // No IndexedDB: start empty.
  }
}

/** Save every successful fetch of `key` (and in-place cache updates) from now on. */
export function persistQuery(queryClient: QueryClient, key: QueryKey) {
  const id = idKey(key);
  let timer: ReturnType<typeof setTimeout> | undefined;
  return queryClient.getQueryCache().subscribe((event) => {
    if (event.type !== "updated" || idKey(event.query.queryKey) !== id) return;
    const { data, dataUpdatedAt, status } = event.query.state;
    if (status !== "success" || data === undefined) return;
    // Coalesce bursts (a refetch right after a patch) into one write, off the
    // critical path of whatever triggered it.
    clearTimeout(timer);
    timer = setTimeout(() => {
      write(key, { version: VERSION, updatedAt: dataUpdatedAt, data }).catch(() => {});
    }, 1000);
  });
}
