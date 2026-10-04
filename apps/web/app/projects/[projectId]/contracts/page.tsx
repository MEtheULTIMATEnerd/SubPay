"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { useData } from "@/lib/store";
import { read } from "@/lib/api";
import { getContractDownloadUrl, retryExtraction, uploadContract } from "@/lib/contracts";
import { LIVE } from "@/lib/env";
import { EmptyState, ErrorState, Icon, Page, PageHeader, ProcessingBadge, cx, fmtDate } from "@/components/ui";

export default function ContractsPage() {
  const db = useData();
  const { projectId } = useParams<{ projectId: string }>();
  const contracts = read.contracts(db, projectId);
  const [error, setError] = useState<{ title: string; body: string } | null>(null);
  const [drag, setDrag] = useState(false);
  const [uploading, setUploading] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  async function upload(files: FileList | null) {
    setError(null);
    const file = files?.[0];
    if (!file || uploading) return;
    setUploading(true);
    try {
      await uploadContract(projectId, file);
    } catch (e) {
      setError({ title: "Upload rejected", body: (e as Error).message });
    } finally {
      setUploading(false);
    }
  }

  async function retry(contractId: string) {
    setError(null);
    try {
      await retryExtraction(contractId);
    } catch (e) {
      setError({ title: "Could not retry", body: (e as Error).message });
    }
  }

  async function download(contractId: string) {
    setError(null);
    try {
      const url = await getContractDownloadUrl(contractId);
      if (!url) throw new Error("The document is not available right now.");
      window.location.assign(url); // a short-lived link that downloads the file
    } catch (e) {
      setError({ title: "Could not download", body: (e as Error).message });
    }
  }

  return (
    <Page wide>
      <PageHeader title="Contract" sub="Upload your subcontract. SubPay turns it into a claim schedule you review line by line." />

      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); void upload(e.dataTransfer.files); }}
        className={cx("mb-6 flex flex-col items-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition", drag ? "border-brand bg-mint" : "border-line bg-white")}
      >
        <Icon.upload className="h-9 w-9 text-sage" />
        <p className="mt-3 font-semibold">Drop your subcontract here</p>
        <p className="text-sm text-muted">PDF or DOCX, up to 25 MB</p>
        <button className="btn-dark mt-4" disabled={uploading} onClick={() => input.current?.click()}>{uploading ? "Uploading…" : "Choose file"}</button>
        <input ref={input} type="file" hidden accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} />
      </div>
      {error && <div className="mb-6"><ErrorState title={error.title} body={error.body} /></div>}

      {contracts.length === 0 ? (
        <EmptyState title="No contract uploaded yet" body="Once uploaded, SubPay extracts claimable items, rates and notice requirements for you to confirm." />
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-surface-2 text-left text-muted">
              <tr>
                <th className="px-5 py-3 font-semibold">Document</th>
                <th className="hidden px-5 py-3 font-semibold md:table-cell">Uploaded</th>
                <th className="px-5 py-3 font-semibold">Extraction</th>
                <th className="px-5 py-3" />
              </tr>
            </thead>
            <tbody>
              {contracts.map((c) => {
                const items = db.contract_items.filter((i) => i.contract_id === c.id);
                const confirmed = items.filter((i) => i.review_status === "confirmed").length;
                return (
                  <tr key={c.id} className="border-t border-line align-top">
                    <td className="px-5 py-4">
                      <div className="flex gap-3">
                        <Icon.doc className="h-6 w-6 shrink-0 text-muted" />
                        <div className="min-w-0">
                          <p className="break-all font-semibold">{c.original_filename}</p>
                          <p className="text-xs text-muted">
                            {c.original_filename.split(".").pop()!.toUpperCase()} · {(c.size_bytes / 1_048_576).toFixed(1)} MB{c.page_count ? ` · ${c.page_count} pages` : ""}
                          </p>
                          <p className="text-xs text-muted md:hidden">Uploaded {fmtDate(c.created_at)}</p>
                        </div>
                      </div>
                    </td>
                    <td className="hidden px-5 py-4 text-muted md:table-cell">{fmtDate(c.created_at)}<br /><span className="text-xs">by {read.actor(db, c.uploaded_by)}</span></td>
                    <td className="px-5 py-4">
                      <ProcessingBadge status={c.processing_status} />
                      {c.processing_status === "ready" && <p className="mt-1 text-xs text-muted">{items.length} items · {confirmed} confirmed</p>}
                      {c.error && <p className="mt-1 max-w-xs text-xs text-red">{c.error}</p>}
                    </td>
                    <td className="px-5 py-4 text-right">
                      {c.processing_status === "ready" && (
                        <Link href={`/projects/${projectId}/contracts/${c.id}/items`} className="btn-primary btn-sm">Review items</Link>
                      )}
                      {c.processing_status === "failed" && <button className="btn-outline btn-sm" onClick={() => void retry(c.id)}>Retry</button>}
                      {LIVE && <button className="btn-outline btn-sm ml-2" onClick={() => void download(c.id)}>Download</button>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-4 text-xs text-muted">
        {LIVE
          ? "Your contract is stored privately. Extracted items are AI drafts until a person confirms them."
          : "Prototype: files are not stored — only their details. Extraction uses a deterministic mock AI provider."}
      </p>
    </Page>
  );
}
