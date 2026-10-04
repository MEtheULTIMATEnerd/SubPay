"use client";
// Application layout + route protection. Unauthenticated users only see /login and /signup.
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useDb } from "@/lib/store";
import { read, setNotification, markAllRead } from "@/lib/api";
import { initAuth, signOut, useAuth } from "@/lib/auth";
import type { Db } from "@/lib/types";
import { Icon, Loading, Logo, cx, fmtDateTime } from "./ui";

const PUBLIC = ["/login", "/signup"];

export function AppShell({ children }: { children: ReactNode }) {
  const db = useDb();
  const auth = useAuth();
  const path = usePathname();
  const router = useRouter();
  const isPublic = PUBLIC.includes(path);
  // Until the saved session has been checked, nobody counts as signed in.
  const ready = Boolean(db) && auth.ready;
  const user = db && auth.ready ? read.me(db) : null;

  useEffect(() => initAuth(), []);

  useEffect(() => {
    if (!ready) return;
    if (!user && !isPublic) router.replace(`/login?next=${encodeURIComponent(path)}`);
    if (user && isPublic) {
      const next = new URLSearchParams(window.location.search).get("next");
      router.replace(next?.startsWith("/") && !next.startsWith("//") ? next : "/dashboard");
    }
  }, [ready, user, isPublic, path, router]);

  if (!db || !ready || (!user && !isPublic) || (user && isPublic)) return <Loading />;
  if (isPublic) return <>{children}</>;

  return (
    <div className="flex min-h-screen flex-col">
      <TopBar db={db} />
      <main className="flex-1">{children}</main>
      <footer className="no-print px-4 py-6 text-center text-xs text-muted sm:px-8">
        SubPay prototype · AI suggests, you approve. SubPay never submits a claim on its own and does not give legal advice.
      </footer>
    </div>
  );
}

function TopBar({ db }: { db: Db }) {
  const path = usePathname();
  const user = read.me(db)!;
  const org = read.org(db);
  const pid = path.match(/^\/projects\/([^/]+)/)?.[1];
  const project = pid && pid !== "new" ? read.project(db, pid) : null;
  // Menus close on navigation: an open menu only counts on the path it was opened from.
  const [open, setOpen] = useState<{ which: "bell" | "user"; path: string } | null>(null);
  const menu = open?.path === path ? open.which : null;
  const setMenu = (which: "bell" | "user" | null) => setOpen(which && { which, path });

  return (
    <header className="no-print sticky top-0 z-30 bg-ink text-white">
      <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
        <Link href="/dashboard" aria-label="SubPay home"><Logo /></Link>
        <nav className="ml-2 hidden items-center gap-1 text-sm md:flex">
          <NavLink href="/dashboard" active={path === "/dashboard"}>Dashboard</NavLink>
          <NavLink href="/projects" active={path === "/projects" || path === "/projects/new"}>Projects</NavLink>
        </nav>
        {project && <span className="ml-1 truncate text-sm text-sage">· {project.name}</span>}
        <div className="ml-auto flex items-center gap-1">
          <span className="mr-2 hidden text-sm text-sage lg:inline">{org.name}</span>
          <Bell db={db} open={menu === "bell"} toggle={() => setMenu(menu === "bell" ? null : "bell")} />
          <div className="relative">
            <button
              onClick={() => setMenu(menu === "user" ? null : "user")}
              className="flex h-9 w-9 items-center justify-center rounded-full bg-ink-3 text-sm font-semibold hover:bg-brand-dark"
              aria-label="Account menu"
              aria-expanded={menu === "user"}
            >
              {user.full_name.split(" ").map((s) => s[0]).join("").slice(0, 2)}
            </button>
            {menu === "user" && (
              <div className="absolute right-0 mt-2 w-60 overflow-hidden rounded-xl border border-line bg-white text-ink-2 shadow-lg">
                <div className="border-b border-line px-4 py-3">
                  <p className="font-semibold">{user.full_name}</p>
                  <p className="text-xs text-muted">{user.email}</p>
                  <p className="mt-1 text-xs text-muted">{org.name} · {user.role}</p>
                </div>
                <Link href="/profile" className="block px-4 py-2.5 text-sm hover:bg-surface">Profile & settings</Link>
                <button onClick={() => void signOut()} className="block w-full px-4 py-2.5 text-left text-sm hover:bg-surface">Sign out</button>
              </div>
            )}
          </div>
        </div>
      </div>
      {/* mobile primary nav */}
      <nav className="flex gap-1 border-t border-ink-3/60 px-3 py-1.5 text-sm md:hidden">
        <NavLink href="/dashboard" active={path === "/dashboard"}>Dashboard</NavLink>
        <NavLink href="/projects" active={path.startsWith("/projects")}>Projects</NavLink>
      </nav>
    </header>
  );
}

function NavLink({ href, active, children }: { href: string; active: boolean; children: ReactNode }) {
  return (
    <Link href={href} className={cx("rounded-full px-3 py-1.5", active ? "bg-ink-3 text-white" : "text-sage hover:text-white")}>
      {children}
    </Link>
  );
}

function Bell({ db, open, toggle }: { db: Db; open: boolean; toggle: () => void }) {
  const list = read.notifications(db);
  const unread = list.filter((n) => n.status === "unread").length;
  return (
    <div className="relative">
      <button onClick={toggle} className="relative rounded-full p-2 hover:bg-ink-3" aria-label={`Notifications, ${unread} unread`} aria-expanded={open}>
        <Icon.bell className="h-6 w-6" />
        {unread > 0 && (
          <span className="absolute right-0.5 top-0.5 flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-brand px-1 text-[10px] font-bold">{unread}</span>
        )}
      </button>
      {open && (
        <div className="fixed inset-x-3 top-16 mt-1 overflow-hidden rounded-xl border border-line bg-white text-ink-2 shadow-lg sm:absolute sm:inset-x-auto sm:right-0 sm:top-auto sm:w-96">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <p className="font-semibold">Notifications</p>
            {unread > 0 && <button onClick={markAllRead} className="text-xs link">Mark all read</button>}
          </div>
          <ul className="max-h-[60vh] overflow-y-auto">
            {list.length === 0 && <li className="px-4 py-8 text-center text-sm text-muted">You&apos;re all caught up.</li>}
            {list.map((n) => (
              <li key={n.id} className={cx("flex gap-3 border-b border-line px-4 py-3 last:border-0", n.status === "unread" && "bg-mint/50")}>
                <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", n.status === "unread" ? "bg-brand" : "bg-transparent")} />
                <div className="min-w-0 flex-1">
                  {n.href ? (
                    <Link href={n.href} onClick={() => setNotification(n.id, "read")} className="font-semibold hover:underline">{n.title}</Link>
                  ) : <p className="font-semibold">{n.title}</p>}
                  <p className="text-sm text-muted">{n.body}</p>
                  <p className="mt-1 text-xs text-muted">{fmtDateTime(n.created_at)}</p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1 text-xs">
                  <button className="text-muted hover:text-ink-2" onClick={() => setNotification(n.id, n.status === "unread" ? "read" : "unread")}>
                    {n.status === "unread" ? "Read" : "Unread"}
                  </button>
                  <button className="text-muted hover:text-red" onClick={() => setNotification(n.id, "dismissed")}>Dismiss</button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
