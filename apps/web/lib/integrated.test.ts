import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { integratedClient } from "./integrated";
import { DELETE } from "../app/api/integrated/[...path]/route";

const TOKEN = "test-only-local-token-not-a-real-secret-12345";
const fetchMock = vi.fn();
const project = { id: "p1", name: "Actual site", description: "Test" };
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => vi.unstubAllGlobals());
const respond = (body: unknown, status = 200) => fetchMock.mockResolvedValueOnce(Response.json(body, { status }));

test("token is required, carried only in a request header, and never put in storage", async () => {
  expect(() => integratedClient("")).toThrow(/token/);
  const storage = { setItem: vi.fn(), getItem: vi.fn() };
  vi.stubGlobal("localStorage", storage); vi.stubGlobal("sessionStorage", storage);
  respond([]);
  await integratedClient(TOKEN).projects();
  expect(fetchMock).toHaveBeenCalledWith("/api/integrated/projects", expect.objectContaining({
    headers: { Authorization: `Bearer ${TOKEN}` }, cache: "no-store", credentials: "omit",
  }));
  expect(storage.setItem).not.toHaveBeenCalled();
  expect(storage.getItem).not.toHaveBeenCalled();
});
test("project creation uses real API fields", async () => {
  respond(project);
  expect(await integratedClient(TOKEN).createProject(" Actual site ", "Test")).toEqual(project);
  expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify({ name: "Actual site", description: "Test" }) });
});
test("project selection retrieves selected project, contracts and evidence", async () => {
  respond(project); respond([]); respond([]);
  const api = integratedClient(TOKEN);
  expect(await api.project("p1")).toEqual(project);
  expect(await api.contracts("p1")).toEqual([]);
  expect(await api.evidence("p1")).toEqual([]);
  expect(fetchMock.mock.calls.map(call => call[0])).toEqual([
    "/api/integrated/projects/p1", "/api/integrated/projects/p1/contracts", "/api/integrated/projects/p1/evidence",
  ]);
});
test("contract upload sends the actual file with a browser multipart boundary", async () => {
  const file = new File(["actual test bytes"], "contract.pdf", { type: "application/pdf" });
  respond({ id: "c1" });
  await integratedClient(TOKEN).uploadContract("p1", file);
  const options = fetchMock.mock.calls[0][1];
  expect(options.body.get("file").name).toBe("contract.pdf");
  expect(await options.body.get("file").text()).toBe("actual test bytes");
  expect(options.headers["Content-Type"]).toBeUndefined();
});
test("contract source and items come from selected endpoints", async () => {
  respond({ id: "c1", extracted_text: "Real extracted content" }); respond([{ id: "i1" }]);
  const api = integratedClient(TOKEN);
  expect((await api.contract("p1", "c1")).extracted_text).toBe("Real extracted content");
  expect(await api.items("p1", "c1")).toEqual([{ id: "i1" }]);
});
test("item editing and confirm/reject/reopen use backend statuses", async () => {
  const api = integratedClient(TOKEN);
  respond({}); await api.editItem("p1", "c1", "i1", "Edited description");
  for (const status of ["confirmed", "rejected", "draft"] as const) {
    respond({}); await api.reviewItem("p1", "c1", "i1", status);
  }
  expect(fetchMock.mock.calls.map(call => [call[1].method, JSON.parse(call[1].body)])).toEqual([
    ["PATCH", { description: "Edited description" }], ["POST", { status: "confirmed" }],
    ["POST", { status: "rejected" }], ["POST", { status: "draft" }],
  ]);
});
test("evidence upload does not request analysis", async () => {
  respond({ id: "e1", processing_status: "uploaded" });
  const result = await integratedClient(TOKEN).uploadEvidence("p1", new File(["image"], "test.png", { type: "image/png" }));
  expect(result.processing_status).toBe("uploaded");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/integrated/projects/p1/evidence");
});
test("empty lists are kept empty, never replaced by demo data", async () => {
  respond([]); expect(await integratedClient(TOKEN).projects()).toEqual([]);
});
test("authentication, API validation and network errors are useful", async () => {
  const api = integratedClient(TOKEN);
  respond({ detail: "Local access token required" }, 401);
  await expect(api.projects()).rejects.toThrow(/Authentication failed/);
  respond({ detail: "Matching PDF\/DOCX extension and MIME type required" }, 415);
  await expect(api.contracts("p1")).rejects.toThrow(/415/);
  fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
  await expect(api.projects()).rejects.toThrow(/Cannot reach the local server/);
});
test("contract and item deletion call DELETE on the selected records", async () => {
  const api = integratedClient(TOKEN);
  fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
  await api.deleteContract("p1", "c1");
  await api.deleteItem("p1", "c1", "i1");
  expect(fetchMock.mock.calls.map(call => [call[1].method, call[0]])).toEqual([
    ["DELETE", "/api/integrated/projects/p1/contracts/c1"],
    ["DELETE", "/api/integrated/projects/p1/contracts/c1/items/i1"],
  ]);
});
test("bridge forwards only contract and item deletes, and passes a 204 through", async () => {
  vi.stubEnv("SUBPAY_INTEGRATED_UI_ENABLED", "true");
  const id = "00000000-0000-4000-8000-000000000001";
  const call = (path: string) => DELETE(
    new Request(`http://127.0.0.1:3101/api/integrated/${path}`, { method: "DELETE", headers: { host: "127.0.0.1:3101", authorization: `Bearer ${TOKEN}` } }),
    { params: Promise.resolve({ path: path.split("/") }) },
  );
  fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
  expect((await call(`projects/${id}/contracts/${id}`)).status).toBe(204);
  expect((await call(`projects/${id}/contracts/${id}/items/${id}`)).status).toBe(204);
  expect((await call(`projects/${id}`)).status).toBe(404);
  expect((await call(`projects/${id}/evidence/${id}`)).status).toBe(404);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  vi.unstubAllEnvs();
});
