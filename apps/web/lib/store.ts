// Browser-persisted mock database. Stands in for Supabase until the real
// backend is wired up; everything goes through lib/api.ts, never this directly.
// ponytail: single localStorage blob (~5MB cap); swap for Supabase, not IndexedDB.
import { useSyncExternalStore } from "react";
import type { Db } from "./types";
import { seed, SEED_VERSION } from "./seed";

const KEY = "subpay-db";
let db: Db | null = null;
const listeners = new Set<() => void>();

export function getDb(): Db {
  if (db) return db;
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
    const parsed = raw ? (JSON.parse(raw) as Db) : null;
    db = parsed?.version === SEED_VERSION ? parsed : { ...seed(), session: parsed?.session ?? null };
  } catch {
    db = seed();
  }
  return db;
}

export function commit(mutate: (d: Db) => void) {
  const next = structuredClone(getDb());
  mutate(next);
  db = next;
  try {
    if (typeof localStorage !== "undefined") localStorage.setItem(KEY, JSON.stringify(db));
  } catch (e) {
    console.warn("SubPay demo storage is full; changes kept in memory only.", e);
  }
  listeners.forEach((l) => l());
}

export function resetDb(session: Db["session"] = null) {
  commit((d) => Object.assign(d, seed(), { session }));
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

/** Undefined during SSR/hydration; the app shell shows a loader until then. */
export function useDb(): Db | undefined {
  return useSyncExternalStore(subscribe, getDb, () => undefined);
}

/** For pages inside the authenticated shell, which only renders once data is loaded. */
export const useData = () => useDb()!;
