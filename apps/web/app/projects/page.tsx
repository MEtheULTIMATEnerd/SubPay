"use client";
import { useEffect, useState } from "react";
import { useData } from "@/lib/store";
import { read } from "@/lib/api";
import { refreshProjects } from "@/lib/projects";
import { NewProjectButton, ProjectCard } from "@/components/projects";
import { EmptyState, Icon, Page, PageHeader, cx } from "@/components/ui";

export default function ProjectsPage() {
  const db = useData();
  const [tab, setTab] = useState<"active" | "archived">("active");
  const [q, setQ] = useState("");
  const all = read.projects(db);

  // Pick up projects colleagues have added since sign-in. The cached list shows meanwhile.
  useEffect(() => void refreshProjects().catch(() => {}), []);
  const list = all
    .filter((p) => p.status === tab)
    .filter((p) => `${p.name} ${p.client_name} ${p.site_address}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <Page>
      <PageHeader title="Projects" sub="Every job your business is claiming on." right={<NewProjectButton />} />
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="inline-flex rounded-full border border-line bg-white p-1 text-sm">
          {(["active", "archived"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)} className={cx("rounded-full px-4 py-1.5 capitalize", tab === t ? "bg-ink text-white" : "text-muted")}>
              {t} ({all.filter((p) => p.status === t).length})
            </button>
          ))}
        </div>
        <div className="relative sm:w-72">
          <Icon.search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input className="input pl-9" placeholder="Search projects" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      {list.length ? (
        <div className="grid gap-4 md:grid-cols-2">{list.map((p) => <ProjectCard key={p.id} db={db} p={p} />)}</div>
      ) : (
        <EmptyState title={q ? "No projects match your search" : `No ${tab} projects`} action={tab === "active" && !q ? <NewProjectButton /> : undefined} />
      )}
    </Page>
  );
}
