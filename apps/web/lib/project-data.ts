// Loads everything a project's screens need from the API when a project is
// opened (live mode). In demo mode there is nothing to load.
import { useEffect, useSyncExternalStore } from "react";
import { refreshContracts } from "./contracts";
import { LIVE } from "./env";
import { refreshEvidence, resetEvidenceState } from "./evidence";

type Status = { ready: boolean; error: string | null };

const READY: Status = { ready: true, error: null };
const LOADING: Status = { ready: false, error: null };

const statuses = new Map<string, Status>();
const listeners = new Set<() => void>();

function setStatus(projectId: string, status: Status) {
  statuses.set(projectId, status);
  listeners.forEach((listener) => listener());
}
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** Fetch the project's data. The first load gates the screens; later ones refresh quietly. */
export async function loadProjectData(projectId: string): Promise<void> {
  if (!LIVE) return;
  const first = !statuses.get(projectId)?.ready;
  if (first) setStatus(projectId, LOADING);
  try {
    await Promise.all([refreshContracts(projectId), refreshEvidence(projectId)]);
    setStatus(projectId, READY);
  } catch (err) {
    // A failed quiet refresh keeps showing what was already loaded.
    if (first) setStatus(projectId, { ready: false, error: (err as Error).message });
  }
}

/** For tests and sign-out: forget what has been loaded. */
export function resetProjectData() {
  statuses.clear();
  resetEvidenceState();
}

export function useProjectData(projectId: string): Status & { reload: () => void } {
  const status = useSyncExternalStore(
    subscribe,
    () => (LIVE ? (statuses.get(projectId) ?? LOADING) : READY),
    () => (LIVE ? LOADING : READY),
  );
  useEffect(() => void loadProjectData(projectId), [projectId]);
  return { ...status, reload: () => void loadProjectData(projectId) };
}
