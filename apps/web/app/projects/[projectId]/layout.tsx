"use client";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useData } from "@/lib/store";
import { read } from "@/lib/api";
import { StatusPill } from "@/components/projects";
import { ErrorState, Page, cx } from "@/components/ui";

const TABS = [
  ["Overview", ""],
  ["Contract", "/contracts"],
  ["Evidence", "/evidence"],
  ["Review", "/review"],
  ["Claims", "/claims"],
  ["Audit trail", "/audit"],
] as const;

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const db = useData();
  const { projectId } = useParams<{ projectId: string }>();
  const path = usePathname();
  const project = read.project(db, projectId);

  if (!project)
    return (
      <Page>
        {/* Same response whether it doesn't exist or belongs to another organisation. */}
        <ErrorState title="Project not found" body="It may have been removed, or you don't have access to it." action={<Link href="/projects" className="link">Back to projects</Link>} />
      </Page>
    );

  const base = `/projects/${projectId}`;
  return (
    <>
      <div className="no-print border-b border-line bg-white">
        <div className="mx-auto max-w-7xl px-4 pt-4 sm:px-8">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h2 className="text-lg font-semibold">{project.name}</h2>
            <StatusPill status={project.status} />
            <span className="text-sm text-muted">{project.client_name}</span>
          </div>
          <nav className="-mb-px mt-3 flex gap-1 overflow-x-auto text-sm [scrollbar-width:none]">
            {TABS.map(([label, seg]) => {
              const href = base + seg;
              const active = seg ? path.startsWith(href) : path === base;
              return (
                <Link
                  key={label}
                  href={href}
                  className={cx("shrink-0 border-b-2 px-3 py-2.5 font-medium", active ? "border-brand text-ink-2" : "border-transparent text-muted hover:text-ink-2")}
                >
                  {label}
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
      {project.status === "archived" && (
        <div className="no-print bg-amber-bg px-4 py-2 text-center text-sm text-amber">This project is archived. Restore it from Overview to keep working on it.</div>
      )}
      {children}
    </>
  );
}
