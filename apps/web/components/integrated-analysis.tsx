"use client";
import React, { useEffect, useRef, useState } from "react";
import { integratedClient, type LocalAnalysis, type LocalEvidence, type LocalMatch } from "../lib/integrated";

type Client = ReturnType<typeof integratedClient>;
export const ANALYSIS_CONSENT = "This will send the selected image to OpenAI GPT-4o-mini for analysis.\n\nThe request may incur an API charge.\n\nAI observations are suggestions and do not establish construction completion or compliance.\n\nIf the server is configured for mock analysis, results will be labelled MOCK instead.";
export const CATEGORIES = ["objects_certain", "objects_possible", "activities_certain", "activities_possible"];

export function AnalysisView({ rows }: { rows: LocalAnalysis[] }) {
  const row = rows.at(-1);
  if (!row) return <p>No analysis yet.</p>;
  return <div>
    <p><strong>{row.provider === "mock" || row.structured_data?.mock ? "MOCK — not real AI" : row.provider}</strong> / {row.model}</p>
    <p>Analysis status: {row.status}{row.processed_at && ` · Processed ${new Date(row.processed_at).toLocaleString("en-AU")}`}</p>
    {row.status === "processing" ? <p>Analysis in progress. Refresh to check status; do not submit again.</p>
      : row.status === "failed" ? <p role="alert">Analysis failed: {row.error || "No results available."}</p>
      : row.status === "ready" && row.structured_data ? <>
        {!CATEGORIES.some(k => row.structured_data!.observations[k]?.length) && <p>Analysis completed with no construction observations.</p>}
        {CATEGORIES.map(category => <div key={category}><h4>{category}</h4><ul>{row.structured_data!.observations[category]?.map((text, i) => <li key={i}>{text}</li>)}</ul></div>)}
      </> : <p>No completed observations available.</p>}
  </div>;
}

export function EvidenceAnalysis({ api, pid, evidence }: { api: Client; pid: string; evidence: LocalEvidence }) {
  const [rows, setRows] = useState<LocalAnalysis[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const locked = useRef(false);
  useEffect(() => {
    let active = true;
    api.observations(pid, evidence.id).then(value => { if (active) setRows(value); })
      .catch(() => { if (active) setError("Could not load persisted observations."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, pid, evidence.id, evidence.processing_status]);
  async function refresh() { setRows(await api.observations(pid, evidence.id)); }
  async function analyse() {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(""); setMessage("");
    let approved = false;
    try {
      await api.analyse(pid, evidence.id, () => { approved = window.confirm(`${evidence.original_filename}\n\n${ANALYSIS_CONSENT}`); return approved; });
      if (approved) { await refresh(); setMessage("Analysis request completed; persisted results shown below."); }
    } catch (err) {
      setError(`${err instanceof Error ? err.message : "Analysis failed."} No retry was made. Refresh status before considering another request.`);
      await refresh().catch(() => {});
    } finally { locked.current = false; setBusy(false); }
  }
  const processing = evidence.processing_status === "processing" || rows.at(-1)?.status === "processing";
  return <div>
    {!rows.length && <p>{evidence.processing_status === "uploaded" ? "Uploaded — awaiting analysis" : `Stored processing status: ${evidence.processing_status}`}</p>}
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "12px 0" }}>
      <button disabled={busy || processing || loading} onClick={() => void analyse()}>Analyse with AI</button>
      <button disabled={busy} onClick={() => { setError(""); void refresh().catch(() => setError("Could not refresh observations.")); }}>Refresh analysis status</button>
    </div>
    {busy && <p role="status">Waiting for analysis. Do not resubmit.</p>}
    {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
    {loading ? <p role="status">Loading persisted observations...</p> : <AnalysisView rows={rows} />}
  </div>;
}

export function MatchScore({ score }: { score: number }) {
  return <p>Lexical relevance score: {score} (heuristic, not a probability or completion percentage)</p>;
}

export function MatchesAndPackages({ api, pid, evidence }: { api: Client; pid: string; evidence: LocalEvidence[] }) {
  const [matches, setMatches] = useState<LocalMatch[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState("");
  const [reportDocument, setReportDocument] = useState("");
  const lock = useRef(false);
  const reportUrl = useRef("");
  useEffect(() => {
    let active = true;
    api.matches(pid).then(rows => { if (active) setMatches(rows); }).catch(() => { if (active) setError("Could not load matches."); });
    return () => { active = false; if (reportUrl.current) URL.revokeObjectURL(reportUrl.current); };
  }, [api, pid]);
  async function run(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    if (reportUrl.current) { URL.revokeObjectURL(reportUrl.current); reportUrl.current = ""; setReport(""); setReportDocument(""); }
    try { await action(); } catch (err) { setError(err instanceof Error ? err.message : "Request failed."); }
    finally { lock.current = false; setBusy(false); }
  }
  async function download(format: "json" | "html") {
    const blob = await api.package(pid, format);
    if (format === "json") {
      const url = URL.createObjectURL(blob); const link = document.createElement("a");
      link.href = url; link.download = `subpay-${pid}-draft.json`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } else {
      // Blob navigations do not inherit response CSP headers: embed restrictive policy.
      const html = await blob.text();
      if (!html.includes("<head>")) throw new Error("Invalid printable report response.");
      const policy = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">`;
      const safe = html.replace("<head>", `<head>${policy}`);
      reportUrl.current = URL.createObjectURL(new Blob([safe], { type: "text/html" })); setReportDocument(safe); setReport(reportUrl.current);
    }
  }
  return <>
    <section aria-labelledby="matches-heading"><h2 id="matches-heading">4. Match Suggestions</h2>
      <p>Suggestions identify potentially relevant evidence. They do not establish completed work or payment entitlement.</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}><button disabled={busy} onClick={() => void run(async () => { await api.generateMatches(pid); setMatches(await api.matches(pid)); })}>Generate Match Suggestions</button>
        <button disabled={busy} onClick={() => void run(async () => setMatches(await api.matches(pid)))}>Refresh matches</button></div>
      {!matches.length && <p>No suggestions. Confirm contract items and use eligible non-mock persisted observations, then generate suggestions.</p>}
      {matches.map(match => <article key={match.id} style={{ borderTop: "1px solid #cbd9d2", padding: "16px 0" }}>
        <h3>{match.item_description}</h3><p>{evidence.find(e => e.id === match.evidence_id)?.original_filename || match.evidence_id}</p>
        <p><strong>{match.review_status}</strong> · {match.is_current ? "Current source" : "STALE — not eligible for draft support"}</p>
        <MatchScore score={match.score} /><p>{match.explanation}</p>
        <ul>{match.supporting_observations.map((o, i) => <li key={i}>{o.group}: {o.text}</li>)}</ul>
        <p>{match.observation_provider} / {match.observation_model}</p>
        {match.reviewed_at && <p>Reviewed by {match.reviewed_by} · {new Date(match.reviewed_at).toLocaleString("en-AU")}</p>}
        <div style={{ display: "flex", gap: 8 }}>{(match.review_status === "pending" ? ["confirm", "reject"] : ["reopen"]).map(action => <button key={action} disabled={busy || (action === "confirm" && !match.is_current)} onClick={() => void run(async () => { await api.reviewMatch(pid, match.id, action as "confirm" | "reject" | "reopen"); setMatches(await api.matches(pid)); })}>{action === "confirm" ? "Confirm match" : action === "reject" ? "Reject match" : "Reopen match"}</button>)}</div>
      </article>)}
    </section>
    <section aria-labelledby="packages-heading"><h2 id="packages-heading">5. Draft Claim Package</h2>
      <p>DRAFT for review. AI observations are not proof of completion. Scores are not probabilities; human confirmation is not independent certification. Quantities, quality, compliance and payment entitlement require independent verification. SubPay does not certify or submit claims.</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}><button disabled={busy} onClick={() => void run(() => download("json"))}>Download Draft JSON Package</button><button disabled={busy} onClick={() => void run(() => download("html"))}>View / Print Draft Report</button></div>
      {report && <><p><a href={report} target="_blank" rel="noopener noreferrer">Open printable report</a></p><iframe title="Draft claim-support report" srcDoc={reportDocument} sandbox="allow-modals" style={{ width: "100%", height: 600, border: "1px solid #cbd9d2" }} /></>}
    </section>
    {busy && <p role="status">Updating records or preparing draft package...</p>}{error && <p role="alert">{error}</p>}
  </>;
}
