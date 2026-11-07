"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Bookmark,
  Database,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  PackageSearch,
  Radar,
  Sun,
  TrendingUp,
  X,
} from "lucide-react";
import { useAuth } from "./AuthProvider";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/products", label: "Products", icon: PackageSearch },
  { href: "/trending", label: "Trending", icon: TrendingUp },
  { href: "/categories", label: "Categories", icon: Radar },
  { href: "/watchlist", label: "Watchlist", icon: Bookmark },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/sources", label: "Data sources", icon: Database },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);

  useEffect(() => {
    const stored = window.localStorage.getItem("trendscope.theme");
    if (stored === "light" || stored === "dark") {
      setTheme(stored);
    } else {
      setTheme(window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    }
  }, []);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      window.localStorage.setItem("trendscope.theme", next);
    } catch {
      /* preference is cosmetic */
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="btn btn-sm h-8 w-8 !p-0"
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
      title="Toggle theme"
    >
      {theme === "dark" ? (
        <Sun className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  );
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const { user, logout, isAdmin } = useAuth();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const nav = (
    <nav className="flex flex-col gap-0.5" aria-label="Main">
      {NAV.map((item) => {
        const Icon = item.icon;
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`nav-item ${active ? "nav-item-active" : ""}`}
            aria-current={active ? "page" : undefined}
          >
            <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );

  const brand = (
    <Link href="/" className="flex items-center gap-2.5" aria-label="TrendScope home">
      <span className="flex h-8 w-8 items-center justify-center rounded-md bg-accent text-accent-ink">
        <Radar className="h-4 w-4" aria-hidden="true" />
      </span>
      <span className="leading-tight">
        <span className="block text-sm font-semibold tracking-tight">TrendScope</span>
        <span className="block text-[0.63rem] font-medium uppercase tracking-[0.16em] text-muted">
          AU product intelligence
        </span>
      </span>
    </Link>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_minmax(0,1fr)]">
      {/* Desktop sidebar */}
      <aside className="hidden border-r border-line bg-surface lg:flex lg:flex-col lg:gap-6 lg:p-4">
        {brand}
        {nav}
        <div className="mt-auto space-y-3">
          <div className="rounded-md border border-line bg-bg p-3">
            <p className="eyebrow">Phase 1</p>
            <p className="mt-1 text-xs leading-relaxed text-muted">
              Mock and CSV sources. Every synthetic record is labelled.
            </p>
          </div>
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">{user?.display_name || user?.email}</p>
              <p className="text-[0.68rem] uppercase tracking-wide text-muted">{user?.role}</p>
            </div>
            <button
              type="button"
              onClick={logout}
              className="btn btn-sm h-8 w-8 !p-0"
              title="Sign out"
              aria-label="Sign out"
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      </aside>

      {/* Mobile header */}
      <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-2.5 lg:hidden">
        {brand}
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <button
            type="button"
            className="btn btn-sm h-8 w-8 !p-0"
            onClick={() => setOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </header>

      {/* Mobile drawer */}
      {open ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/40"
            aria-label="Close navigation"
            onClick={() => setOpen(false)}
          />
          <div className="absolute left-0 top-0 flex h-full w-72 flex-col gap-6 border-r border-line bg-surface p-4 shadow-xl">
            <div className="flex items-center justify-between">
              {brand}
              <button
                type="button"
                className="btn btn-sm h-8 w-8 !p-0"
                onClick={() => setOpen(false)}
                aria-label="Close navigation"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            {nav}
            <div className="mt-auto space-y-3">
              <div className="flex items-center justify-between gap-2 border-t border-line pt-3">
                <div className="min-w-0">
                  <p className="truncate text-xs font-medium">{user?.display_name || user?.email}</p>
                  <p className="text-[0.68rem] uppercase tracking-wide text-muted">{user?.role}</p>
                </div>
                <button type="button" onClick={logout} className="btn btn-sm" title="Sign out">
                  <LogOut className="h-4 w-4" aria-hidden="true" /> Sign out
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <div className="min-w-0">
        <div className="hidden items-center justify-end gap-2 border-b border-line bg-surface px-8 py-2.5 lg:flex">
          {isAdmin ? (
            <span className="pill pill-accent mr-1" title="Your role">
              admin
            </span>
          ) : null}
          <ThemeToggle />
        </div>
        <main className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </main>
        <footer className="mx-auto w-full max-w-[1400px] px-4 pb-8 text-xs leading-relaxed text-muted sm:px-6 lg:px-8">
          Growth is derived from relative search interest, not sales. Scores are estimates and
          shrink toward the midpoint when coverage is low. Synthetic records are demo data, not
          market facts.
        </footer>
      </div>
    </div>
  );
}
