import { beforeEach, expect, test, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getSession: vi.fn() }));

vi.mock("./env", () => ({ LIVE: true, API_URL: "http://api.test", SUPABASE_URL: "http://supabase.test", SUPABASE_ANON_KEY: "anon" }));
vi.mock("./supabase", () => ({ supabase: () => ({ auth: { getSession: mocks.getSession } }) }));

import { ApiError } from "./errors";
import { apiFetch, setUnauthorizedHandler } from "./http";

const fetchMock = vi.fn();
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const lastCall = () => {
  const [url, init] = fetchMock.mock.calls.at(-1)!;
  return { url: String(url), init: init as RequestInit, headers: init.headers as Record<string, string> };
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  mocks.getSession.mockResolvedValue({ data: { session: { access_token: "user-token" } } });
  setUnauthorizedHandler(null);
});

test("sends the signed-in user's token to the versioned API", async () => {
  fetchMock.mockResolvedValue(json(200, { items: [] }));
  await expect(apiFetch("/projects", { query: { status: "active", limit: 20, offset: undefined } })).resolves.toEqual({ items: [] });

  const { url, init, headers } = lastCall();
  expect(url).toBe("http://api.test/api/v1/projects?status=active&limit=20");
  expect(init.method).toBe("GET");
  expect(headers.Authorization).toBe("Bearer user-token");
  expect(init.body).toBeUndefined();
});

test("sends a JSON body on writes", async () => {
  fetchMock.mockResolvedValue(json(201, { id: "p1" }));
  await apiFetch("/projects", { method: "POST", body: { name: "Hume St Tower" } });

  const { init, headers } = lastCall();
  expect(init.method).toBe("POST");
  expect(headers["Content-Type"]).toBe("application/json");
  expect(JSON.parse(init.body as string)).toEqual({ name: "Hume St Tower" });
});

test("sends a file upload as a form and lets the browser set the content type", async () => {
  fetchMock.mockResolvedValue(json(201, { id: "c1" }));
  const form = new FormData();
  form.append("file", new File(["%PDF-"], "contract.pdf", { type: "application/pdf" }));
  await apiFetch("/projects/p1/contracts", { method: "POST", form });

  const { init, headers } = lastCall();
  expect(init.body).toBe(form);
  expect(headers["Content-Type"]).toBeUndefined(); // the multipart boundary is added by the browser
  expect(headers.Authorization).toBe("Bearer user-token");
});

test("makes no request when nobody is signed in", async () => {
  mocks.getSession.mockResolvedValue({ data: { session: null } });
  await expect(apiFetch("/me")).rejects.toMatchObject({ status: 401, code: "unauthenticated" });
  expect(fetchMock).not.toHaveBeenCalled();
});

test("turns the API's error shape into an ApiError", async () => {
  fetchMock.mockResolvedValue(
    json(422, { error: { code: "validation_error", message: "Request validation failed", details: [{ field: "name", message: "Required" }] } }),
  );
  const error = await apiFetch("/projects", { method: "POST", body: {} }).catch((e) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 422, code: "validation_error", message: "Request validation failed", details: [{ field: "name", message: "Required" }] });
});

test("uses a safe message when the error body is not JSON", async () => {
  fetchMock.mockResolvedValue(new Response("<html>Bad gateway</html>", { status: 502 }));
  await expect(apiFetch("/me")).rejects.toMatchObject({ status: 502, message: "Something went wrong. Please try again." });
});

test("reports an unreachable server as 503", async () => {
  fetchMock.mockRejectedValue(new TypeError("fetch failed"));
  await expect(apiFetch("/me")).rejects.toMatchObject({ status: 503, code: "service_unavailable" });
});

test("tells the app when the API rejects the session", async () => {
  const handler = vi.fn();
  setUnauthorizedHandler(handler);
  fetchMock.mockResolvedValue(json(401, { error: { code: "unauthenticated", message: "Your session is invalid or has expired. Sign in again." } }));
  await expect(apiFetch("/me")).rejects.toMatchObject({ status: 401 });
  expect(handler).toHaveBeenCalledOnce();

  handler.mockClear();
  fetchMock.mockResolvedValue(json(404, { error: { code: "not_found", message: "Project not found" } }));
  await expect(apiFetch("/projects/x")).rejects.toMatchObject({ status: 404 });
  expect(handler).not.toHaveBeenCalled();
});
