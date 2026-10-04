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

// ---- uploads that report progress use XMLHttpRequest ----
class FakeXhr {
  static last: FakeXhr;
  method = ""; url = ""; headers: Record<string, string> = {}; body: unknown = null;
  status = 0; responseText = "";
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null; onerror: (() => void) | null = null; onabort: (() => void) | null = null;
  constructor() { FakeXhr.last = this; }
  open(method: string, url: string) { this.method = method; this.url = url; }
  setRequestHeader(name: string, value: string) { this.headers[name] = value; }
  send(body: unknown) { this.body = body; }
  progress(loaded: number, total: number) { this.upload.onprogress?.({ lengthComputable: true, loaded, total }); }
  finish(status: number, body: unknown) { this.status = status; this.responseText = typeof body === "string" ? body : JSON.stringify(body); this.onload?.(); }
}
const fileForm = () => {
  const form = new FormData();
  form.append("file", new File(["photo"], "site.jpg", { type: "image/jpeg" }));
  return form;
};
/** Wait until apiFetch has read the session and sent the request. */
const sent = () => vi.waitFor(() => expect(FakeXhr.last?.body).toBeTruthy());

test("an upload with a progress callback reports how much has been sent", async () => {
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  const progress: number[] = [];
  const form = fileForm();
  const result = apiFetch<{ id: string }>("/projects/p1/evidence", { method: "POST", form, onUploadProgress: (f) => progress.push(f) });
  await sent();

  const xhr = FakeXhr.last;
  expect(xhr.method).toBe("POST");
  expect(xhr.url).toBe("http://api.test/api/v1/projects/p1/evidence");
  expect(xhr.headers).toEqual({ Authorization: "Bearer user-token" }); // no Content-Type: the browser adds the boundary
  expect(xhr.body).toBe(form);
  expect(fetchMock).not.toHaveBeenCalled();

  xhr.progress(25, 100);
  xhr.progress(80, 100);
  xhr.finish(201, { id: "e1" });
  await expect(result).resolves.toEqual({ id: "e1" });
  expect(progress).toEqual([0.25, 0.8, 1]);
});

test("a failed upload gives the same errors as any other request", async () => {
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  const handler = vi.fn();
  setUnauthorizedHandler(handler);

  let result = apiFetch("/projects/p1/evidence", { method: "POST", form: fileForm(), onUploadProgress: () => {} }).catch((e) => e);
  await sent();
  FakeXhr.last.finish(415, { error: { code: "unsupported_media_type", message: "That file type is not supported." } });
  expect(await result).toMatchObject({ status: 415, code: "unsupported_media_type", message: "That file type is not supported." });

  result = apiFetch("/projects/p1/evidence", { method: "POST", form: fileForm(), onUploadProgress: () => {} }).catch((e) => e);
  await vi.waitFor(() => expect(FakeXhr.last.status).toBe(0));
  await sent();
  FakeXhr.last.finish(502, "<html>Bad gateway</html>");
  expect(await result).toMatchObject({ status: 502, message: "Something went wrong. Please try again." });

  result = apiFetch("/projects/p1/evidence", { method: "POST", form: fileForm(), onUploadProgress: () => {} }).catch((e) => e);
  await vi.waitFor(() => expect(FakeXhr.last.status).toBe(0));
  await sent();
  FakeXhr.last.onerror?.();
  expect(await result).toMatchObject({ status: 503, code: "service_unavailable" });
  expect(handler).not.toHaveBeenCalled();

  result = apiFetch("/projects/p1/evidence", { method: "POST", form: fileForm(), onUploadProgress: () => {} }).catch((e) => e);
  await vi.waitFor(() => expect(FakeXhr.last.status).toBe(0));
  await sent();
  FakeXhr.last.finish(401, { error: { code: "unauthenticated", message: "Sign in again." } });
  expect(await result).toMatchObject({ status: 401 });
  expect(handler).toHaveBeenCalledOnce();
});

test("without a progress callback an upload still uses fetch", async () => {
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  fetchMock.mockResolvedValue(json(201, { id: "c1" }));
  await apiFetch("/projects/p1/contracts", { method: "POST", form: fileForm() });
  expect(fetchMock).toHaveBeenCalledOnce();
});

test("a public request needs no session and sends no token", async () => {
  mocks.getSession.mockClear();
  mocks.getSession.mockResolvedValue({ data: { session: null } });
  const handler = vi.fn();
  setUnauthorizedHandler(handler);

  fetchMock.mockResolvedValue(json(200, { organisation_name: "Org A Formwork" }));
  await expect(apiFetch("/invitations/some-invite-code", { auth: false })).resolves.toEqual({ organisation_name: "Org A Formwork" });
  expect(lastCall().headers.Authorization).toBeUndefined();
  expect(mocks.getSession).not.toHaveBeenCalled();

  // a refusal on a public request is not a reason to sign anyone out
  fetchMock.mockResolvedValue(json(401, { error: { code: "unauthenticated", message: "No" } }));
  await expect(apiFetch("/invitations/some-invite-code", { auth: false })).rejects.toMatchObject({ status: 401 });
  expect(handler).not.toHaveBeenCalled();
});
