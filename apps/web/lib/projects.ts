// Project management for the whole app (F02). Components call these functions
// and never talk to the API or the mock directly.
//
// live mode: the FastAPI service is the source of truth. The local store keeps a
//            copy of the organisation's projects, so pages (and the features
//            that still run on mock data) can read them without waiting.
// demo mode: the original prototype behaviour, simulated in lib/api.ts.
import * as mock from "./api";
import { LIVE } from "./env";
import { isApiError } from "./errors";
import { apiFetch } from "./http";
import { commit } from "./store";
import type { Db, Project } from "./types";

export type ProjectInput = Pick<Project, "name" | "client_name" | "site_address" | "start_date" | "end_date">;

const PAGE_SIZE = 200;

// Only these fields are ever sent. The API sets organisation, creator and status itself.
const editable = (input: ProjectInput): ProjectInput => ({
  name: input.name.trim(),
  client_name: input.client_name.trim(),
  site_address: (input.site_address ?? "").trim(),
  start_date: input.start_date || null,
  end_date: input.end_date || null,
});

function currentOrganisationId(d: Db): string | null {
  const profile = d.session && d.profiles.find((p) => p.id === d.session!.profile_id);
  return profile ? profile.organisation_id : null;
}

function store(project: Project) {
  commit((d) => {
    const index = d.projects.findIndex((p) => p.id === project.id);
    if (index === -1) d.projects.push(project);
    else d.projects[index] = project;
  });
}

function forget(id: string) {
  commit((d) => { d.projects = d.projects.filter((p) => p.id !== id); });
}

/** Replace the local copy of this organisation's projects with what the API returns. */
export async function refreshProjects(): Promise<void> {
  if (!LIVE) return;
  const projects: Project[] = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const { items } = await apiFetch<{ items: Project[] }>("/projects", { query: { limit: PAGE_SIZE, offset } });
    projects.push(...items);
    if (items.length < PAGE_SIZE) break;
  }
  commit((d) => {
    const organisationId = currentOrganisationId(d);
    if (!organisationId) return;
    d.projects = [...d.projects.filter((p) => p.organisation_id !== organisationId), ...projects];
  });
}

/** Drop the signed-in organisation's projects, and the contracts under them, from the local copy (used at sign-out). */
export function clearCachedProjects(d: Db) {
  const organisationId = currentOrganisationId(d);
  if (!organisationId) return;
  const projectIds = new Set(d.projects.filter((p) => p.organisation_id === organisationId).map((p) => p.id));
  const contractIds = new Set(d.contracts.filter((c) => projectIds.has(c.project_id)).map((c) => c.id));
  d.contract_items = d.contract_items.filter((i) => !contractIds.has(i.contract_id));
  d.contracts = d.contracts.filter((c) => !projectIds.has(c.project_id));
  d.projects = d.projects.filter((p) => !projectIds.has(p.id));
}

/** Returns the new project's id. */
export async function createProject(input: ProjectInput): Promise<string> {
  if (!LIVE) return mock.createProject(input);
  mock.validateProject(input);
  const project = await apiFetch<Project>("/projects", { method: "POST", body: editable(input) });
  store(project);
  mock.logAudit(project.id, "project.created", "project", project.id, { name: project.name });
  return project.id;
}

export async function updateProject(id: string, input: ProjectInput): Promise<void> {
  if (!LIVE) return mock.updateProject(id, input);
  mock.validateProject(input);
  store(await write(id, () => apiFetch<Project>(`/projects/${id}`, { method: "PATCH", body: editable(input) })));
  mock.logAudit(id, "project.updated", "project", id);
}

export async function setProjectStatus(id: string, status: Project["status"]): Promise<void> {
  if (!LIVE) return mock.setProjectStatus(id, status);
  const action = status === "archived" ? "archive" : "restore";
  store(await write(id, () => apiFetch<Project>(`/projects/${id}/${action}`, { method: "POST" })));
  mock.logAudit(id, status === "archived" ? "project.archived" : "project.restored", "project", id);
}

/** If the API says the project is gone (or no longer ours), stop showing it. */
async function write(id: string, request: () => Promise<Project>): Promise<Project> {
  try {
    return await request();
  } catch (err) {
    if (isApiError(err) && err.status === 404) forget(id);
    throw err;
  }
}
