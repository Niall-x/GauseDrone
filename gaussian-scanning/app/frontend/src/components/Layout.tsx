import clsx from "clsx";
import { Cpu, FolderInput, HardDrive, Layers, Plus } from "lucide-react";
import { NavLink, Outlet } from "react-router";
import { api } from "../api/client";
import { usePoll } from "../lib/hooks";

export function Layout() {
  const { data: sys } = usePoll(api.system, 5000);

  const nav = [
    { to: "/", label: "Runs", icon: <Layers className="size-4" />, end: true },
    { to: "/captures", label: "Captures", icon: <FolderInput className="size-4" /> },
  ];

  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-panel">
        <div className="flex items-center gap-2.5 px-4 py-4">
          <img src="/favicon.svg" alt="" className="size-7" />
          <div>
            <div className="text-sm font-semibold leading-tight">Splat Lab</div>
            <div className="text-[11px] leading-tight text-faint">GauseDrone</div>
          </div>
        </div>
        <div className="px-3 pb-3">
          <NavLink
            to="/runs/new"
            className="flex h-9 w-full items-center justify-center gap-2 rounded-md bg-accent text-sm font-medium text-bg transition-colors hover:bg-accent-strong"
          >
            <Plus className="size-4" /> New run
          </NavLink>
        </div>
        <nav className="flex flex-col gap-0.5 px-2">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  isActive ? "bg-panel-2 text-fg" : "text-muted hover:bg-panel-2/60 hover:text-fg",
                )
              }
            >
              {n.icon}
              {n.label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto space-y-2 border-t border-line px-4 py-3 text-[11px] text-faint">
          {sys ? (
            <>
              <div className="flex items-center gap-1.5" title={sys.gpu}>
                <Cpu className="size-3.5 shrink-0" />
                <span className="truncate">{sys.gpu || "no GPU found"}</span>
              </div>
              {sys.gpu_mem_total_mb != null && (
                <div className="h-1 overflow-hidden rounded-full bg-line">
                  <div
                    className="h-full bg-muted"
                    style={{ width: `${(100 * (sys.gpu_mem_used_mb ?? 0)) / sys.gpu_mem_total_mb}%` }}
                  />
                </div>
              )}
              <div className="flex items-center gap-1.5" title={sys.data_dir}>
                <HardDrive className="size-3.5 shrink-0" />
                {sys.disk_free_gb} GB free
              </div>
              <div className="truncate" title={`${sys.colmap}\ntorch ${sys.torch}, gsplat ${sys.gsplat}`}>
                {sys.git_commit && <span className="font-mono">{sys.git_commit}</span>}
              </div>
            </>
          ) : (
            <span>connecting…</span>
          )}
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
