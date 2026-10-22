import { afterEach, beforeEach, expect, test, vi } from "vitest";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AnalysisView, EvidenceAnalysis, MatchScore, ANALYSIS_CONSENT } from "../components/integrated-analysis";
import { integratedClient, type LocalAnalysis } from "./integrated";

const token = "test-only-local-token-not-a-real-secret-12345";
const fetchMock = vi.fn();
const api = () => integratedClient(token);
const ready: LocalAnalysis = { id: "a", provider: "openai", model: "gpt-4o-mini", status: "ready", error: null, processed_at: "2026-10-23T00:00:00Z", structured_data: { mock: false, observations: { objects_certain: ["Circuit breakers"], objects_possible: [], activities_certain: [], activities_possible: [] } } };
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => vi.unstubAllGlobals());

test("analysis requires explicit consent and cancellation sends no request", async () => {
  const consent = vi.fn(() => false);
  await api().analyse("p", "e", consent);
  expect(consent).toHaveBeenCalledOnce(); expect(fetchMock).not.toHaveBeenCalled();
  expect(ANALYSIS_CONSENT).toContain("API charge");
  expect(ANALYSIS_CONSENT).toContain("OpenAI GPT-4o-mini");
});
test("concurrent repeated clicks issue exactly one inference request without retry", async () => {
  let finish!: (response: Response) => void;
  fetchMock.mockReturnValue(new Promise<Response>(resolve => { finish = resolve; }));
  const client = api(); const consent = vi.fn(() => true);
  const first = client.analyse("p", "e", consent);
  await client.analyse("p", "e", consent);
  expect(fetchMock).toHaveBeenCalledOnce(); expect(consent).toHaveBeenCalledOnce();
  finish(Response.json(ready)); await first;
});
test("failed analysis is not retried or substituted with mock output", async () => {
  fetchMock.mockResolvedValue(Response.json({ detail: "Provider failed" }, { status: 502 }));
  await expect(api().analyse("p", "e", () => true)).rejects.toThrow(/Provider failed/);
  expect(fetchMock).toHaveBeenCalledOnce();
});
test("initial render and evidence upload never infer", async () => {
  renderToStaticMarkup(React.createElement(EvidenceAnalysis, { api: api(), pid: "p", evidence: { id: "e", original_filename: "x.png", processing_status: "uploaded", uploaded_at: "now", content_type: "image/png", size: 12 } }));
  expect(fetchMock).not.toHaveBeenCalled();
  fetchMock.mockResolvedValue(Response.json({ id: "e" }));
  await api().uploadEvidence("p", new File(["image"], "x.png"));
  expect(fetchMock.mock.calls[0][0]).not.toContain("analyse");
});
test("actual observations, empty results, mock provenance and failures are distinct", () => {
  const view = (rows: LocalAnalysis[]) => renderToStaticMarkup(React.createElement(AnalysisView, { rows }));
  expect(view([])).toContain("No analysis yet");
  expect(view([ready])).toContain("Circuit breakers");
  expect(view([ready])).toContain("gpt-4o-mini");
  expect(view([{ ...ready, structured_data: { mock: false, observations: {} } }])).toContain("no construction observations");
  expect(view([{ ...ready, provider: "mock" }])).toContain("MOCK");
  const failed = view([{ ...ready, status: "failed", structured_data: null, error: "Timeout" }]);
  expect(failed).toContain("Analysis failed"); expect(failed).not.toContain("Circuit breakers");
  expect(view([{ ...ready, status: "processing" }])).toContain("Analysis in progress");
});
test("match generation/review use backend endpoints and refreshed review state", async () => {
  const client = api();
  fetchMock.mockResolvedValueOnce(Response.json({ created: 1 }));
  await client.generateMatches("p");
  for (const action of ["confirm", "reject", "reopen"] as const) {
    fetchMock.mockResolvedValueOnce(Response.json({})); await client.reviewMatch("p", "m", action);
  }
  fetchMock.mockResolvedValueOnce(Response.json([{ id: "m", review_status: "confirmed" }]));
  expect((await client.matches("p"))[0].review_status).toBe("confirmed");
  expect(fetchMock.mock.calls.map(c => c[0])).toEqual([
    "/api/integrated/projects/p/matches/generate", "/api/integrated/projects/p/matches/m/confirm",
    "/api/integrated/projects/p/matches/m/reject", "/api/integrated/projects/p/matches/m/reopen", "/api/integrated/projects/p/matches",
  ]);
  const score = renderToStaticMarkup(React.createElement(MatchScore, { score: 1 }));
  expect(score).toContain("Lexical relevance score"); expect(score).not.toContain("AI confidence");
});
test("JSON and HTML downloads preserve authenticated backend bytes without token URLs/storage", async () => {
  const storage = { setItem: vi.fn() }; vi.stubGlobal("localStorage", storage); vi.stubGlobal("sessionStorage", storage);
  const client = api();
  for (const format of ["json", "html"] as const) {
    const text = format === "html" ? "<!doctype html><html>escaped report</html>" : '{"status":"draft"}';
    fetchMock.mockResolvedValueOnce(new Response(text));
    expect(await (await client.package("p", format)).text()).toBe(text);
    const [url, options] = fetchMock.mock.calls.at(-1)!;
    expect(url).toBe(`/api/integrated/projects/p/claim-package.${format}`);
    expect(url).not.toContain(token); expect(options.headers.Authorization).toBe(`Bearer ${token}`);
  }
  expect(storage.setItem).not.toHaveBeenCalled();
});
