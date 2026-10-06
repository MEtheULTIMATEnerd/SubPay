"use client";
import Link from "next/link";
import { useEffect } from "react";
import { useData } from "@/lib/store";
import { read, readiness } from "@/lib/api";
import { refreshProjects } from "@/lib/projects";
import { NewProjectButton, ProjectCard } from "@/components/projects";
import { Banner, EmptyState, Page, PageHeader, cx } from "@/components/ui";

export default function Dashboard() {
  const db = useData();
  const user = read.me(db)!;
  const org = read.org(db);
  const projects = read.projects(db);

  // Pick up projects colleagues have added since sign-in. The cached list shows meanwhile.
  useEffect(() => void refreshProjects().catch(() => {}), []);
  const active = projects.filter((p) => p.status === "active");
  const hour = new Date().getHours();

  // Cross-project "do these first" list, derived from the live claim readiness.
  const todo = active.flatMap((p) =>
    read.claims(db, p.id).filter((c) => c.status !== "exported").flatMap((c) => {
      const r = readiness(db, c.id);
      const base = `/projects/${p.id}`;
      return [
        r.pendingMatches > 0 && { text: `Review ${r.pendingMatches} AI-suggested evidence links`, sub: `${p.name} · ${c.name}`, href: `${base}/review` },
        ...r.notices.filter((n) => n.days != null && n.days <= 14).map((n) => ({
          text: `${n.text}`, sub: `${n.label} · ${n.days! < 0 ? "date passed" : `closes in ${n.days} days`}`, href: `${base}/claims/${c.id}`, urgent: n.days! <= 7,
        })),
        r.counts.missing > 0 && { text: `${r.counts.missing} claim lines have no evidence`, sub: `${p.name} · ${c.name}`, href: `${base}/review` },
      ].filter(Boolean) as { text: string; sub: string; href: string; urgent?: boolean }[];
    }),
  );

  return (
    <Page>
      <PageHeader
        title={`Good ${hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening"}, ${user.full_name.split(" ")[0]}`}
        sub={`${org.name} · ${user.role === "owner" ? "Owner" : "Member"}`}
        right={<NewProjectButton />}
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="eyebrow">Active projects</h2>
            <Link href="/projects" className="text-sm link">All projects</Link>
          </div>
          {active.length ? (
            <div className="grid gap-4">{active.map((p) => <ProjectCard key={p.id} db={db} p={p} />)}</div>
          ) : (
            <EmptyState title="No active projects" body="Create a project to upload your subcontract and start capturing evidence." action={<NewProjectButton />} />
          )}
        </section>

        <section>
          <h2 className="eyebrow mb-3">Do these things first</h2>
          <div className="card p-2">
            {todo.length === 0 && <p className="px-4 py-8 text-center text-sm text-muted">Nothing needs your attention right now.</p>}
            <ol>
              {todo.slice(0, 6).map((t, i) => (
                <li key={i}>
                  <Link href={t.href} className="flex gap-3 rounded-xl px-4 py-3 hover:bg-surface">
                    <span className={cx("flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold", t.urgent ? "bg-red-bg text-red" : "bg-surface-2 text-muted")}>{i + 1}</span>
                    <span>
                      <span className="block text-sm font-medium">{t.text}</span>
                      <span className="block text-xs text-muted">{t.sub}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </div>
        </section>
      </div>

      <div className="mt-8">
        <Banner title="AI suggests. You approve. SubPay never submits a claim on its own." body="Every approved link is stored with its source file, time and author." />
      </div>
    </Page>
  );
}
