"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useData } from "@/lib/store";
import { createClaim, read, readiness } from "@/lib/api";
import { EmptyState, ErrorState, Icon, Page, PageHeader, Progress, cx, fmtDate, money } from "@/components/ui";

export default function ClaimsPage() {
  const db = useData();
  const router = useRouter();
  const { projectId } = useParams<{ projectId: string }>();
  const claims = read.claims(db, projectId).slice().reverse();
  const [error, setError] = useState("");

  function create() {
    try { router.push(`/projects/${projectId}/claims/${createClaim(projectId)}`); } catch (e) { setError((e as Error).message); }
  }

  return (
    <Page wide>
      <PageHeader
        title="Progress claims"
        sub="Check what is proven before you send each claim to the builder."
        right={<button className="btn-primary" onClick={create}><Icon.plus className="h-4 w-4" />New claim</button>}
      />
      {error && <div className="mb-5"><ErrorState title={error} /></div>}
      {claims.length === 0 ? (
        <EmptyState title="No claims yet" body="A new claim includes every confirmed contract item." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {claims.map((c) => {
            const r = readiness(db, c.id);
            return (
              <Link key={c.id} href={`/projects/${projectId}/claims/${c.id}`} className="card p-6 hover:border-sage">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-lg font-semibold">{c.name}</p>
                    <p className="text-sm text-muted">Due to the builder {fmtDate(c.due_date)} · {r.rows.length} lines · {money(r.total)}</p>
                  </div>
                  <span className={cx("pill", c.status === "exported" ? "bg-mint text-brand-dark" : "bg-surface-2 text-muted")}>{c.status === "exported" ? "Package exported" : "Not yet submitted"}</span>
                </div>
                <div className="mt-5 mb-2 flex justify-between text-sm"><span className="text-muted">Evidence support coverage</span><span className="font-semibold">{r.coverage}%</span></div>
                <Progress value={r.coverage} />
              </Link>
            );
          })}
        </div>
      )}
    </Page>
  );
}
