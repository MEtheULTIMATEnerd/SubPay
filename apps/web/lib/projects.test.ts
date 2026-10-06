// Live mode: projects come from /api/v1/projects. The API is replaced by a fake.
import { beforeEach, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("./env", () => ({ LIVE: true, API_URL: "http://api.test", SUPABASE_URL: "http://supabase.test", SUPABASE_ANON_KEY: "anon" }));
vi.mock("./http", () => ({ apiFetch: mocks.apiFetch, setUnauthorizedHandler: vi.fn() }));
vi.mock("./supabase", () => ({ supabase: () => { throw new Error("not used"); } }));

import { read } from "./api";
import { ApiError } from "./errors";
import { createProject, refreshProjects, setProjectStatus, updateProject } from "./projects";
import { commit, getDb, resetDb } from "./store";
import type { Project } from "./types";

const USER_ID = "a0000000-0000-4000-8000-000000000001";
const ORG_ID = "0b6f3c1e-6d2f-4c0a-9d53-1f0f5a6f7a01";
const at = "2026-10-04T05:00:00Z";
const project = (over: Partial<Project> = {}): Project => ({
  id: "5a0d8a0e-2c9b-4a55-8a8e-0a2b9a6c1d22", organisation_id: ORG_ID, name: "Real Tower", client_name: "Builder", site_address: "1 Real St",
  status: "active", start_date: "2026-03-02", end_date: null, created_by: USER_ID, created_at: at, updated_at: at, ...over,
});
const INPUT = { name: " Real Tower ", client_name: "Builder", site_address: "1 Real St", start_date: "2026-03-02", end_date: null };
const mine = () => read.projects(getDb());

beforeEach(() => {
  mocks.apiFetch.mockReset();
  resetDb(null);
  // A signed-in real user, as lib/auth.ts leaves the store after sign-in.
  commit((d) => {
    d.organisations.push({ id: ORG_ID, name: "Org A Formwork", created_at: at, updated_at: at });
    d.profiles.push({ id: USER_ID, organisation_id: ORG_ID, email: "alex@subpay.test", full_name: "Alex Owner", role: "owner", created_at: at, updated_at: at });
    d.session = { profile_id: USER_ID };
  });
});

test("refresh replaces this organisation's projects and leaves other data alone", async () => {
  commit((d) => { d.projects.push(project({ id: "stale", name: "Deleted elsewhere" })); });
  const seeded = getDb().projects.filter((p) => p.organisation_id !== ORG_ID).length;
  mocks.apiFetch.mockResolvedValue({ items: [project(), project({ id: "second", name: "Second Job", status: "archived" })] });

  await refreshProjects();

  expect(mocks.apiFetch).toHaveBeenCalledWith("/projects", { query: { limit: 200, offset: 0 } });
  expect(mine().map((p) => p.name).sort()).toEqual(["Real Tower", "Second Job"]);
  expect(getDb().projects.filter((p) => p.organisation_id !== ORG_ID)).toHaveLength(seeded);
});

test("refresh keeps asking until it has every page", async () => {
  const page = (n: number, from: number) => ({ items: Array.from({ length: n }, (_, i) => project({ id: `p${from + i}` })) });
  mocks.apiFetch.mockResolvedValueOnce(page(200, 0)).mockResolvedValueOnce(page(3, 200));

  await refreshProjects();

  expect(mocks.apiFetch).toHaveBeenCalledTimes(2);
  expect(mocks.apiFetch).toHaveBeenLastCalledWith("/projects", { query: { limit: 200, offset: 200 } });
  expect(mine()).toHaveLength(203);
});

test("create sends only the editable fields and shows the project straight away", async () => {
  mocks.apiFetch.mockResolvedValue(project());
  const id = await createProject({ ...INPUT, organisation_id: "someone-else", status: "archived", created_by: "x" } as never);

  expect(id).toBe(project().id);
  expect(mocks.apiFetch).toHaveBeenCalledWith("/projects", {
    method: "POST",
    body: { name: "Real Tower", client_name: "Builder", site_address: "1 Real St", start_date: "2026-03-02", end_date: null },
  });
  expect(read.project(getDb(), id)?.name).toBe("Real Tower");
  expect(read.audit(getDb(), id)[0].action).toBe("project.created");
});

test("obviously invalid input is rejected before any request", async () => {
  await expect(createProject({ ...INPUT, name: "  " })).rejects.toThrow("Project name is required");
  await expect(createProject({ ...INPUT, start_date: "2026-06-01", end_date: "2026-05-01" })).rejects.toThrow("End date must be after start date");
  expect(mocks.apiFetch).not.toHaveBeenCalled();
});

test("an API error leaves the local copy unchanged", async () => {
  mocks.apiFetch.mockRejectedValue(new ApiError(503, "Can't reach the SubPay server. Check your connection and try again."));
  await expect(createProject(INPUT)).rejects.toThrow(/Can't reach the SubPay server/);
  expect(mine()).toEqual([]);
});

test("update saves through the API and updates the local copy", async () => {
  commit((d) => { d.projects.push(project()); });
  mocks.apiFetch.mockResolvedValue(project({ name: "Renamed Tower", end_date: "2026-12-18" }));

  await updateProject(project().id, { ...INPUT, name: "Renamed Tower", end_date: "2026-12-18" });

  expect(mocks.apiFetch).toHaveBeenCalledWith(`/projects/${project().id}`, {
    method: "PATCH",
    body: { name: "Renamed Tower", client_name: "Builder", site_address: "1 Real St", start_date: "2026-03-02", end_date: "2026-12-18" },
  });
  expect(read.project(getDb(), project().id)).toMatchObject({ name: "Renamed Tower", end_date: "2026-12-18" });
});

test("archive and restore use their own endpoints", async () => {
  commit((d) => { d.projects.push(project()); });

  mocks.apiFetch.mockResolvedValue(project({ status: "archived" }));
  await setProjectStatus(project().id, "archived");
  expect(mocks.apiFetch).toHaveBeenLastCalledWith(`/projects/${project().id}/archive`, { method: "POST" });
  expect(read.project(getDb(), project().id)?.status).toBe("archived");

  mocks.apiFetch.mockResolvedValue(project({ status: "active" }));
  await setProjectStatus(project().id, "active");
  expect(mocks.apiFetch).toHaveBeenLastCalledWith(`/projects/${project().id}/restore`, { method: "POST" });
  expect(read.project(getDb(), project().id)?.status).toBe("active");
  expect(read.audit(getDb(), project().id).map((a) => a.action)).toEqual(["project.restored", "project.archived"]);
});

test("a project the API no longer knows about disappears from the app", async () => {
  commit((d) => { d.projects.push(project()); });
  mocks.apiFetch.mockRejectedValue(new ApiError(404, "Project not found", "not_found"));

  await expect(updateProject(project().id, INPUT)).rejects.toThrow("Project not found");
  expect(read.project(getDb(), project().id)).toBeNull();
});
