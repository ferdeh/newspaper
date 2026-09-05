"use client";

import {
  Activity, AlertTriangle, BellRing, BookOpenCheck, Boxes, ChevronLeft, ChevronRight, CircleGauge, Database, Flame,
  ListFilter, Map, MapPinned, Menu, Newspaper, PackageSearch, PanelLeftOpen, Radar, Route, Search, Settings,
  ShieldAlert, Smartphone, UserCircle, X, type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

type NavItem = readonly [label: string, href: string, icon: LucideIcon];
type NavGroup = { label: string; items: readonly NavItem[] };

const navGroups: NavGroup[] = [
  {
    label: "Command center",
    items: [
      ["Overview", "/", CircleGauge], ["Situation Map", "/situation-map", Map],
      ["Incidents", "/incidents", AlertTriangle], ["News", "/news", Newspaper],
      ["Product Intelligence", "/product-intelligence", PackageSearch], ["Event Intelligence", "/event-intelligence", Radar],
      ["HSSE", "/hsse", ShieldAlert],
      ["TikTok Early Warning", "/tiktok-early-warning", Flame], ["Alerts", "/alerts", BellRing],
    ],
  },
  {
    label: "TikTok Discovery",
    items: [
      ["Discovery Overview", "/tiktok-discovery", Radar],
      ["TikTok public signals", "/tiktok-discovery/public-signals", Smartphone],
      ["Discovery Keywords", "/tiktok-discovery/keywords", ListFilter],
      ["Manual TikTok Search", "/tiktok-discovery/manual-search", Search],
      ["Discovery Videos", "/tiktok-discovery/videos", Smartphone],
      ["Discovery Runs", "/tiktok-discovery/runs", Activity],
      ["Discovery Settings", "/tiktok-discovery/settings", Settings],
    ],
  },
  { label: "Master Data", items: [["TBBM / Fuel Terminal", "/master-data/tbbm", Database]] },
  { label: "Administration", items: [["System Monitor", "/system", Boxes], ["Settings", "/settings", Settings], ["Documentation", "/documentation", BookOpenCheck]] },
];

function isActive(pathname: string, href: string) {
  return href === "/" || href === "/tiktok-discovery" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
}

function currentTitle(pathname: string) {
  const match = navGroups.flatMap((group) => group.items).find(([, href]) => isActive(pathname, href));
  return match?.[0] ?? "Fuel Intelligence";
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem("fuel-intelligence-sidebar-collapsed") === "true");
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem("fuel-intelligence-sidebar-collapsed", String(next));
      return next;
    });
  };

  return (
    <div className={`app-shell ${collapsed ? "sidebar-is-collapsed" : ""}`}>
      <button
        type="button"
        className={`sidebar-scrim ${mobileOpen ? "is-visible" : ""}`}
        aria-label="Close navigation overlay"
        onClick={() => setMobileOpen(false)}
      />

      <aside className={`app-sidebar ${collapsed ? "is-collapsed" : ""} ${mobileOpen ? "is-mobile-open" : ""}`}>
        <div className="sidebar-brand-row">
          <Link href="/" className="petrofin-brand" onClick={() => setMobileOpen(false)} aria-label="Elnusa Petrofin Fuel Intelligence">
            <span className="petrofin-mark" aria-hidden="true"><span>P</span></span>
            <span className="petrofin-wordmark"><span>elnusa</span><strong>petrofin</strong></span>
          </Link>
          <button type="button" className="sidebar-mobile-close" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X size={19} /></button>
          <button type="button" className="sidebar-collapse-top" onClick={toggleCollapsed} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
        </div>

        <nav className="sidebar-navigation" aria-label="Main navigation">
          {navGroups.map((group) => (
            <div className="sidebar-group" key={group.label}>
              <div className="sidebar-group-label">{group.label}</div>
              <div className="sidebar-group-items">
                {group.items.map(([label, href, Icon]) => {
                  const active = isActive(pathname, href);
                  return (
                    <Link key={href} href={href} title={collapsed ? label : undefined} className={`sidebar-nav-item ${active ? "is-active" : ""}`} aria-current={active ? "page" : undefined} onClick={() => setMobileOpen(false)}>
                      <span className="sidebar-icon" aria-hidden="true"><Icon size={19} strokeWidth={active ? 2.2 : 1.9} /></span>
                      <span className="sidebar-item-label">{label}</span>
                      {active && <ChevronRight className="sidebar-active-caret" size={16} aria-hidden="true" />}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <button type="button" className="sidebar-footer-button" onClick={toggleCollapsed} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} title={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
            {collapsed ? <PanelLeftOpen size={19} /> : <ChevronLeft size={19} />}
            <span>{collapsed ? "" : "Collapse"}</span>
          </button>
          {!collapsed && <div className="sidebar-product-note"><Route size={14} /> Fuel Intelligence</div>}
        </div>
      </aside>

      <main className="app-main min-h-screen bg-transparent text-ink">
        <header className="app-topbar">
          <div className="app-topbar-left">
            <button type="button" className="mobile-menu-button" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu size={20} /></button>
            <div className="topbar-context"><span>Fuel Intelligence</span><strong>{currentTitle(pathname)}</strong></div>
          </div>
          <div className="app-topbar-actions">
            <Link href="/settings" className="topbar-settings-button"><MapPinned size={18} /><span>Integration Settings</span></Link>
            <div className="topbar-profile" aria-label="Current workspace profile">
              <span className="topbar-avatar"><UserCircle size={22} /></span>
              <span className="topbar-profile-copy"><strong>Petrofin</strong><small>Operations</small></span>
            </div>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
