"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { Icon } from "@/components/ui";
import { integratedClient, type LocalProject, type LocalContract, type LocalItem, type LocalEvidence } from "@/lib/integrated";
import styles from "./page.module.css";
import { EvidenceAnalysis, MatchesAndPackages } from "../../components/integrated-analysis";

type Client = ReturnType<typeof integratedClient>;
const date = (value: string) => new Date(value).toLocaleString("en-AU");

export default function IntegratedPage() {
  const [token, setToken] = useState("");
  const [api, setApi] = useState<Client | null>(null);
  const [projects, setProjects] = useState<LocalProject[]>([]);
  const [project, setProject] = useState<LocalProject | null>(null);
  const [contracts, setContracts] = useState<LocalContract[]>([]);
  const [contract, setContract] = useState<LocalContract | null>(null);
  const [items, setItems] = useState<LocalItem[]>([]);
  const [evidence, setEvidence] = useState<LocalEvidence[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function run(label: string, action: () => Promise<void>) {
    setBusy(label); setError(""); setNotice("");
    try { await action(); } catch (err) { setError(err instanceof Error ? err.message : "Local request failed."); }
    finally { setBusy(""); }
  }
  function clearProject() { setProject(null); setContracts([]); setContract(null); setItems([]); setEvidence([]); }
  async function selectProject(client: Client, id: string) {
    clearProject();
    if (!id) return;
    const [p, cs, es] = await Promise.all([client.project(id), client.contracts(id), client.evidence(id)]);
    setProject(p); setContracts(cs); setEvidence(es);
  }
  async function selectContract(id: string) {
    setContract(null); setItems([]);
    if (!api || !project || !id) return;
    const [record, rows] = await Promise.all([api.contract(project.id, id), api.items(project.id, id)]);
    setContract(record); setItems(rows);
  }
  function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run("Connecting", async () => {
      const client = integratedClient(token);
      const rows = await client.projects();
      setApi(client); setProjects(rows); setToken("");
    });
  }
  function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    void run("Creating project", async () => {
      const record = await api!.createProject(String(data.get("name")), String(data.get("description")));
      setProjects(await api!.projects()); await selectProject(api!, record.id); form.reset();
    });
  }
  function upload(event: FormEvent<HTMLFormElement>, kind: "contract" | "evidence") {
    event.preventDefault();
    const form = event.currentTarget;
    const file = new FormData(form).get("file");
    if (!(file instanceof File) || !file.size) { setError("Choose a non-empty file."); return; }
    const limit = (kind === "contract" ? 20 : 10) * 1024 * 1024;
    if (file.size > limit) { setError(`File must be ${kind === "contract" ? 20 : 10} MB or smaller.`); return; }
    void run(kind === "contract" ? "Uploading and extracting contract" : "Uploading evidence", async () => {
      if (kind === "contract") {
        const record = await api!.uploadContract(project!.id, file);
        setContracts(await api!.contracts(project!.id));
        await selectContract(record.id);
        setNotice("Contract saved. Review extracted items before confirming.");
      } else {
        await api!.uploadEvidence(project!.id, file);
        setEvidence(await api!.evidence(project!.id));
        setNotice("Evidence saved. No AI analysis was requested.");
      }
      form.reset();
    });
  }
  function updateItem(item: LocalItem, status?: LocalItem["review_status"], description?: string) {
    void run(status ? "Saving review" : "Saving description", async () => {
      const updated = status
        ? await api!.reviewItem(project!.id, contract!.id, item.id, status)
        : await api!.editItem(project!.id, contract!.id, item.id, description!);
      setItems(rows => rows.map(row => row.id === updated.id ? updated : row));
      setNotice("Contract item saved.");
    });
  }
  function deleteContract() {
    if (!window.confirm(`Delete ${contract!.original_filename}, its items and their match suggestions? This cannot be undone.`)) return;
    void run("Deleting contract", async () => {
      await api!.deleteContract(project!.id, contract!.id);
      setContract(null); setItems([]);
      setContracts(await api!.contracts(project!.id));
      setNotice("Contract deleted. Refresh matches to update the review list.");
    });
  }
  function deleteItem(item: LocalItem) {
    if (!window.confirm(`Delete ${item.item_code || "this item"} and its match suggestions? This cannot be undone.`)) return;
    void run("Deleting item", async () => {
      await api!.deleteItem(project!.id, contract!.id, item.id);
      setItems(rows => rows.filter(row => row.id !== item.id));
      setNotice("Contract item deleted. Refresh matches to update the review list.");
    });
  }
  return <div className={styles.root}>
    <header className={styles.header}><strong>SubPay</strong><Link href="/login">Deterministic demo</Link></header>
    <main className={styles.main}>
      <div className={styles.title}><div><h1>Integrated MVP — Local Development</h1><p>Real local SQLite-backed records. Not a production deployment.</p></div>
        {api && <button disabled={!!busy} onClick={() => { setApi(null); setToken(""); setProjects([]); clearProject(); setError(""); setNotice(""); }}>Disconnect</button>}
      </div>
      {error && <div role="alert" className={styles.error}>{error}</div>}
      <div role="status" aria-live="polite" className={styles.status}>{busy ? `${busy}...` : notice}</div>
      {!api ? <section><h2>Local access</h2><p>Development token only. Kept in memory until disconnect or page reload.</p>
        <form onSubmit={connect} className={styles.connection}>
          <label>Local access token<input type="password" autoComplete="off" required minLength={32} value={token} onChange={e => setToken(e.target.value)} disabled={!!busy} /></label>
          <button disabled={!!busy} type="submit">Connect</button>
        </form></section> : <>
        <section aria-labelledby="projects-heading"><div className={styles.sectionHeading}><h2 id="projects-heading">1. Projects</h2>
          <button title="Refresh projects" aria-label="Refresh projects" disabled={!!busy} onClick={() => void run("Refreshing projects", async () => { setProjects(await api.projects()); if (project) await selectProject(api, project.id); })}><span aria-hidden="true">&#8635;</span></button></div>
          <div className={styles.columns}><div><label>Selected project<select aria-label="Selected project" value={project?.id ?? ""} disabled={!!busy} onChange={e => void run("Loading project", () => selectProject(api, e.target.value))}>
            <option value="">Select a project</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
            {!projects.length && <p>No projects yet.</p>}
            {project && <dl><dt>Project ID</dt><dd>{project.id}</dd><dt>Description</dt><dd>{project.description || "Not recorded"}</dd><dt>Created</dt><dd>{date(project.created_at)}</dd><dt>Updated</dt><dd>{date(project.updated_at)}</dd></dl>}
          </div><form onSubmit={createProject}><h3>New project</h3><label>Project name<input name="name" required maxLength={200} disabled={!!busy} /></label><label>Description<textarea name="description" maxLength={5000} disabled={!!busy} /></label><button type="submit" disabled={!!busy}>Create project</button></form></div>
        </section>
        {!project ? <p>Select or create a project to continue.</p> : <>
          <section aria-labelledby="contracts-heading"><h2 id="contracts-heading">2. Contracts</h2>
            <form className={styles.upload} onSubmit={e => upload(e, "contract")}><label>Contract PDF or DOCX (up to 20 MB)<input type="file" name="file" accept=".pdf,.docx" required disabled={!!busy} /></label><button disabled={!!busy} type="submit"><Icon.upload className="h-4 w-4" />Upload contract</button></form>
            <label>Contract<select aria-label="Contract" disabled={!!busy} value={contract?.id ?? ""} onChange={e => void run("Loading contract", () => selectContract(e.target.value))}><option value="">Select a contract</option>{contracts.map(c => <option key={c.id} value={c.id}>{c.original_filename}</option>)}</select></label>
            {!contracts.length && <p>No contracts uploaded.</p>}
            {contract && <><p>{contract.original_filename} · {date(contract.created_at)} <button type="button" disabled={!!busy} onClick={deleteContract}>Delete contract</button></p>{contract.limitation && <p className={styles.warning}>{contract.limitation} Manual review is required.</p>}
              <details><summary>Extracted document text</summary><pre>{contract.extracted_text || "No readable text was extracted."}</pre></details>
              <h3>Contract items</h3>{!items.length && <p>No extracted items. Manual review is required; manual item entry is not available on this page yet.</p>}
              <div>{items.map(item => <ItemRow key={`${item.id}-${item.updated_at}`} item={item} busy={!!busy} update={updateItem} remove={deleteItem} />)}</div>
            </>}
          </section>
          <section aria-labelledby="evidence-heading"><div className={styles.sectionHeading}><h2 id="evidence-heading">3. Evidence &amp; AI Analysis</h2><button aria-label="Refresh evidence" title="Refresh evidence" disabled={!!busy} onClick={() => void run("Refreshing evidence", async () => setEvidence(await api.evidence(project.id)))}><span aria-hidden="true">&#8635;</span></button></div>
            <form className={styles.upload} onSubmit={e => upload(e, "evidence")}><label>Evidence image (JPEG, PNG or WebP; up to 10 MB)<input type="file" name="file" accept="image/jpeg,image/png,image/webp" required disabled={!!busy} /></label><button type="submit" disabled={!!busy}><Icon.upload className="h-4 w-4" />Upload evidence</button></form>
            {!evidence.length && <p>No evidence uploaded.</p>}
            <ul className={styles.evidence}>{evidence.map(record => <li key={record.id}><strong>{record.original_filename}</strong><p>{record.content_type} · {record.size.toLocaleString()} bytes · {date(record.uploaded_at)}</p><small>{record.id}</small><EvidenceAnalysis api={api} pid={project.id} evidence={record} /></li>)}</ul>
          </section>
          <MatchesAndPackages key={project.id} api={api} pid={project.id} evidence={evidence} />
        </>}
      </>}
    </main>
  </div>;
}

function ItemRow({ item, busy, update, remove }: { item: LocalItem; busy: boolean; update: (item: LocalItem, status?: LocalItem["review_status"], description?: string) => void; remove: (item: LocalItem) => void }) {
  const [description, setDescription] = useState(item.description);
  return <article className={styles.item}><div className={styles.sectionHeading}><h4>{item.item_code || "Contract item"}</h4><strong>{item.review_status}</strong></div><p className={styles.source}>Source: {item.source_reference}</p>
    <form onSubmit={e => { e.preventDefault(); update(item, undefined, description); }}><label>Description<textarea aria-label="Contract item description" value={description} minLength={3} maxLength={2000} required disabled={busy || item.review_status !== "draft"} onChange={e => setDescription(e.target.value)} /></label>
      <div className={styles.actions}>{item.review_status === "draft" ? <><button type="submit" disabled={busy || description === item.description}>Save description</button><button type="button" disabled={busy || description !== item.description} onClick={() => update(item, "confirmed")}><Icon.check className="h-4 w-4" />Confirm</button><button type="button" disabled={busy || description !== item.description} onClick={() => update(item, "rejected")}>Reject</button></> : <button type="button" disabled={busy} onClick={() => update(item, "draft")}>Reopen</button>}<button type="button" disabled={busy} onClick={() => remove(item)}>Delete item</button></div>
    </form><p>{item.quantity !== null ? `Recorded quantity: ${item.quantity} ${item.unit ?? ""}` : "Quantity not recorded"}{item.rate !== null && ` · Recorded rate: ${item.rate}`}{item.amount !== null && ` · Recorded amount: ${item.amount}`}</p>
    {item.reviewed_at && <p>Reviewed by {item.reviewed_by} · {date(item.reviewed_at)}</p>}
  </article>;
}
