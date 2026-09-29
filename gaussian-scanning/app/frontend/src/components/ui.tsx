// Shared building blocks; every screen is composed from these so the app
// stays visually consistent.
import clsx from "clsx";
import { AlertTriangle, CheckCircle2, CircleDashed, Loader2, XCircle, Ban, Clock, PauseCircle, ShieldAlert } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import type { RunStatus, StageStatus } from "../api/client";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  variant = "secondary",
  size = "md",
  loading,
  icon,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        "disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        variant === "primary" && "bg-accent text-bg hover:bg-accent-strong",
        variant === "secondary" && "border border-line-strong bg-panel-2 text-fg hover:bg-line",
        variant === "ghost" && "text-muted hover:bg-panel-2 hover:text-fg",
        variant === "danger" && "border border-bad/40 bg-bad/10 text-bad hover:bg-bad/20",
        className,
      )}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function Card({ className, children, title, actions }: { className?: string; children: ReactNode; title?: ReactNode; actions?: ReactNode }) {
  return (
    <section className={clsx("rounded-lg border border-line bg-panel", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-sm font-semibold text-fg">{title}</h2>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <div className="mt-1 text-sm text-muted">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const STATUS_STYLE: Record<string, { cls: string; icon: ReactNode; label: string }> = {
  pending: { cls: "text-faint border-line", icon: <CircleDashed className="size-3.5" />, label: "Pending" },
  queued: { cls: "text-muted border-line-strong", icon: <Clock className="size-3.5" />, label: "Queued" },
  running: { cls: "text-accent border-accent/40 bg-accent/10", icon: <Loader2 className="size-3.5 animate-spin" />, label: "Running" },
  done: { cls: "text-ok border-ok/30 bg-ok/10", icon: <CheckCircle2 className="size-3.5" />, label: "Done" },
  failed: { cls: "text-bad border-bad/30 bg-bad/10", icon: <XCircle className="size-3.5" />, label: "Failed" },
  cancelled: { cls: "text-warn border-warn/30 bg-warn/10", icon: <Ban className="size-3.5" />, label: "Cancelled" },
  paused: { cls: "text-warn border-warn/30 bg-warn/10", icon: <PauseCircle className="size-3.5" />, label: "Needs attention" },
};

export function StatusBadge({ status }: { status: RunStatus | StageStatus }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.pending;
  return (
    <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium", s.cls)}>
      {s.icon}
      {s.label}
    </span>
  );
}

export function StatusIcon({ status, className }: { status: StageStatus; className?: string }) {
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.pending;
  return <span className={clsx("inline-flex", s.cls.split(" ")[0], className)}>{s.icon}</span>;
}

export function ProgressBar({ value, status, className }: { value: number; status?: StageStatus | RunStatus; className?: string }) {
  const color =
    status === "failed" ? "bg-bad" : status === "cancelled" || status === "paused" ? "bg-warn" : status === "done" ? "bg-ok" : "bg-accent";
  return (
    <div className={clsx("h-1.5 overflow-hidden rounded-full bg-line", className)}>
      <div className={clsx("h-full rounded-full transition-[width] duration-500", color)} style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

export function Field({ label, help, children, htmlFor }: { label: ReactNode; help?: ReactNode; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted">
        {label}
      </label>
      {children}
      {help && <p className="text-xs leading-snug text-faint">{help}</p>}
    </div>
  );
}

const inputCls =
  "h-9 w-full rounded-md border border-line-strong bg-bg px-3 text-sm text-fg placeholder:text-faint " +
  "focus:border-accent focus:outline-none disabled:opacity-50";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={clsx(inputCls, className)} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={clsx(inputCls, "pr-8", className)}>
      {children}
    </select>
  );
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-line px-6 py-14 text-center">
      {icon && <div className="text-faint">{icon}</div>}
      <p className="font-medium">{title}</p>
      {children && <div className="max-w-md text-sm text-muted">{children}</div>}
    </div>
  );
}

export function ErrorBanner({ error, className }: { error?: Error | string | null; className?: string }) {
  if (!error) return null;
  return (
    <div className={clsx("flex items-start gap-2 rounded-md border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad", className)}>
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span className="whitespace-pre-wrap break-words">{typeof error === "string" ? error : error.message}</span>
    </div>
  );
}

/** A problem a stage found in the capture (see pipeline/quality.py). */
export interface Issue {
  kind: string;
  severity: "info" | "warning" | "error";
  title: string;
  detail: string;
  fix: string;
  ranges: { start: number | null; end: number | null; first: string; last: string; frames: number }[];
  frames: number;
}
export type Verdict = "good" | "gaps" | "unreliable";

type WithResult = { status?: string; result?: Record<string, unknown> | null };

export function stageIssues(stage?: WithResult): Issue[] {
  const i = stage?.status === "done" ? stage.result?.issues : null;
  return Array.isArray(i) ? (i as Issue[]) : [];
}

/** The run's verdict comes from the camera-pose check; issues from every finished stage, most severe first. */
export function runQuality(run: { stages: (WithResult & { name: string })[] }): { verdict: Verdict | null; issues: Issue[] } {
  const sfm = run.stages.find((s) => s.name === "sfm");
  const verdict = sfm?.status === "done" ? ((sfm.result?.verdict as Verdict | undefined) ?? null) : null;
  const order = { error: 0, warning: 1, info: 2 };
  const issues = run.stages.flatMap((s) => stageIssues(s)).sort((a, b) => order[a.severity] - order[b.severity]);
  return { verdict, issues };
}

export const VERDICT_STYLE: Record<Verdict, { cls: string; icon: ReactNode; label: string; text: string }> = {
  good: { cls: "text-ok border-ok/30 bg-ok/10", icon: <CheckCircle2 className="size-4" />, label: "Good",
    text: "The camera positions look right for the whole capture." },
  gaps: { cls: "text-warn border-warn/30 bg-warn/10", icon: <AlertTriangle className="size-4" />, label: "Usable, with gaps",
    text: "Parts of the capture are missing or were left out; the rest can be trusted." },
  unreliable: { cls: "text-bad border-bad/30 bg-bad/10", icon: <ShieldAlert className="size-4" />, label: "Unreliable",
    text: "Too many camera positions look wrong to trust the result." },
};

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const v = VERDICT_STYLE[verdict];
  return (
    <span className={clsx("inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium [&_svg]:size-3.5", v.cls)} title={v.text}>
      {v.icon}
      {v.label}
    </span>
  );
}

/** Problems a stage reported as plain strings (`warnings`, runs from before issues existed). */
export function stageWarnings(stage?: { result?: Record<string, unknown> | null }): string[] {
  const w = stage?.result?.warnings;
  return Array.isArray(w) ? w.filter((x): x is string => typeof x === "string") : [];
}

export function WarningList({ warnings, className }: { warnings: string[]; className?: string }) {
  if (!warnings.length) return null;
  return (
    <ul className={clsx("space-y-1.5 rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn", className)}>
      {warnings.map((w) => (
        <li key={w} className="flex items-start gap-2">
          <AlertTriangle className="mt-px size-3.5 shrink-0" />
          <span>{w}</span>
        </li>
      ))}
    </ul>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="min-w-0" title={hint}>
      <div className="text-xs text-faint">{label}</div>
      <div className="truncate font-mono text-sm tabular-nums text-fg">{value ?? "–"}</div>
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("size-5 animate-spin text-muted", className)} />;
}
