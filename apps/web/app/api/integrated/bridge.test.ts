import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { GET, POST } from "./[...path]/route";

const token = "test-only-local-token-not-a-real-secret-12345";
const pid = "11111111-1111-4111-8111-111111111111";
const fetchMock = vi.fn();
function req(path = "projects", over: Record<string, string> = {}, method = "GET") {
  return new Request(`http://127.0.0.1:3101/api/integrated/${path}`, { method,
    headers: { host: "127.0.0.1:3101", Authorization: `Bearer ${token}`, ...over } });
}
const ctx = (path = "projects") => ({ params: Promise.resolve({ path: path.split("/") }) });
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); vi.stubEnv("SUBPAY_INTEGRATED_UI_ENABLED", "true"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
test("bridge is disabled by default", async () => {
  vi.stubEnv("SUBPAY_INTEGRATED_UI_ENABLED", "");
  expect((await GET(req(), ctx())).status).toBe(404);
  expect(fetchMock).not.toHaveBeenCalled();
});
test("missing token and unsafe origins/hosts cannot reach API", async () => {
  expect((await GET(req("projects", { Authorization: "" }), ctx())).status).toBe(401);
  expect((await GET(req("projects", { origin: "http://evil.test" }), ctx())).status).toBe(403);
  expect((await GET(req("projects", { host: "evil.test:3101" }), ctx())).status).toBe(403);
  expect(fetchMock).not.toHaveBeenCalled();
});
test("authenticated allowlisted call uses fixed loopback backend and no cookies", async () => {
  fetchMock.mockResolvedValue(Response.json([]));
  const response = await GET(req(), ctx());
  expect(response.status).toBe(200);
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/integrated/projects", expect.objectContaining({ headers: { Authorization: `Bearer ${token}` }, redirect: "error" }));
});
test("unrelated endpoints and path injection are not forwarded", async () => {
  for (const path of [`projects/${pid}/notifications`, `projects/${pid}/variations`, "../health", "http://evil.test"]) {
    expect((await POST(req(path, {}, "POST"), ctx(path))).status).toBe(404);
  }
  expect(fetchMock).not.toHaveBeenCalled();
});
test("backend auth and network errors do not leak credentials", async () => {
  fetchMock.mockResolvedValueOnce(Response.json({ detail: "Local access token required" }, { status: 401 }));
  expect((await GET(req(), ctx())).status).toBe(401);
  fetchMock.mockRejectedValueOnce(Error("private network detail"));
  const response = await GET(req(), ctx());
  expect(response.status).toBe(502);
  expect(await response.text()).not.toContain(token);
});
test("Stage 6B explicitly allows only authenticated single-image and match actions", async () => {
  for (const path of [`projects/${pid}/evidence/${pid}/analyse`, `projects/${pid}/matches/generate`, `projects/${pid}/matches/${pid}/confirm`, `projects/${pid}/matches/${pid}/reject`, `projects/${pid}/matches/${pid}/reopen`]) {
    fetchMock.mockResolvedValueOnce(Response.json({}));
    expect((await POST(req(path, {}, "POST"), ctx(path))).status).toBe(200);
  }
});
test("HTML download forwards actual bytes, filename and security headers", async () => {
  const path = `projects/${pid}/claim-package.html`;
  const html = "<!doctype html><html><head></head><body>Draft</body></html>";
  fetchMock.mockResolvedValueOnce(new Response(html, { headers: {
    "Content-Type": "text/html; charset=utf-8", "Content-Disposition": 'attachment; filename="draft.html"',
    "Content-Security-Policy": "default-src 'none'",
  } }));
  const response = await GET(req(path), ctx(path));
  expect(await response.text()).toBe(html);
  expect(response.headers.get("content-type")).toContain("text/html");
  expect(response.headers.get("content-disposition")).toContain("draft.html");
  expect(response.headers.get("content-security-policy")).toBe("default-src 'none'");
});
