// Demo mode: projects live in the browser only, as in the original prototype.
import { beforeEach, expect, test, vi } from "vitest";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("./env", () => ({ LIVE: false, API_URL: "", SUPABASE_URL: "", SUPABASE_ANON_KEY: "" }));
vi.mock("./http", () => ({ apiFetch, setUnauthorizedHandler: vi.fn() }));
vi.mock("./supabase", () => ({ supabase: () => { throw new Error("Supabase must not be used in demo mode"); } }));

import { read } from "./api";
import { createProject, refreshProjects, setProjectStatus, updateProject } from "./projects";
import { getDb, resetDb } from "./store";

beforeEach(() => resetDb({ profile_id: "usr-ollie" }));

test("demo mode creates, edits and archives projects locally without calling the API", async () => {
  const id = await createProject({ name: "Demo Job", client_name: "Builder", site_address: "", start_date: null, end_date: null });
  await updateProject(id, { name: "Demo Job 2", client_name: "Builder", site_address: "1 St", start_date: null, end_date: null });
  await setProjectStatus(id, "archived");
  await refreshProjects();

  expect(read.project(getDb(), id)).toMatchObject({ name: "Demo Job 2", status: "archived", organisation_id: "org-kearney" });
  expect(read.projects(getDb()).some((p) => p.name === "Hume St Tower")).toBe(true);
  expect(apiFetch).not.toHaveBeenCalled();
});

test("demo mode surfaces validation errors as rejected promises", async () => {
  await expect(createProject({ name: "", client_name: "B", site_address: "", start_date: null, end_date: null })).rejects.toThrow("Project name is required");
});
