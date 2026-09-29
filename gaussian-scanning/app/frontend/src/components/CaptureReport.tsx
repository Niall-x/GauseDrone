// What the pipeline found wrong with a capture, and what to do about it
// (issues come from pipeline/quality.py). Video captures get a timeline so
// each problem can be traced to the moment to refilm.
import clsx from "clsx";
import { AlertTriangle, Info, RotateCcw, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { api, type Run } from "../api/client";
import { Card, VERDICT_STYLE, runQuality, type Issue } from "./ui";

const SEVERITY: Record<Issue["severity"], { icon: ReactNode; text: string; band: string }> = {
  error: { icon: <XCircle className="size-4" />, text: "text-bad", band: "bg-bad" },
  warning: { icon: <AlertTriangle className="size-4" />, text: "text-warn", band: "bg-warn" },
  info: { icon: <Info className="size-4" />, text: "text-muted", band: "bg-faint" },
};

type Range = Issue["ranges"][number];
const when = (r: Range) =>
  r.start == null ? (r.first === r.last ? r.first : `${r.first} to ${r.last}`) : r.start === r.end ? `${r.start.toFixed(1)} s` : `${r.start.toFixed(1)}–${r.end!.toFixed(1)} s`;

export function CaptureReport({ run, duration }: { run: Run; duration?: number | null }) {
  const { verdict, issues } = runQuality(run);
  const sfm = (run.stages.find((s) => s.name === "sfm")?.result ?? {}) as Record<string, unknown>;
  const [hover, setHover] = useState<number | null>(null);
  if (!verdict && !issues.length) return null;

  const timed = issues.some((i) => i.ranges.some((r) => r.start != null));
  const end = duration || Math.max(0, ...issues.flatMap((i) => i.ranges.map((r) => r.end ?? 0)));
  const v = verdict ? VERDICT_STYLE[verdict] : null;
  const excluded = Number(sfm.excluded_frames ?? 0);

  return (
    <Card title="Capture report">
      <div className="space-y-4 p-4">
        {v && (
          <div className={clsx("flex items-start gap-2 rounded-md border px-3 py-2 text-sm", v.cls)}>
            <span className="mt-0.5 shrink-0">{v.icon}</span>
            <div>
              <span className="font-medium">{v.label}.</span> <span className="text-fg/80">{v.text}</span>
              {excluded > 0 && <span className="text-fg/80"> {excluded} frames with wrong camera positions were left out of training.</span>}
            </div>
          </div>
        )}

        {timed && end > 0 && (
          <div>
            <div className="relative h-6 overflow-hidden rounded bg-line">
              {issues.map((issue, i) =>
                issue.ranges.map((r, j) =>
                  r.start == null ? null : (
                    <div
                      key={`${i}-${j}`}
                      onMouseEnter={() => setHover(i)}
                      onMouseLeave={() => setHover(null)}
                      title={`${issue.title}: ${when(r)}`}
                      className={clsx(
                        "absolute inset-y-0 min-w-[3px]",
                        SEVERITY[issue.severity].band,
                        issue.severity === "info" ? "opacity-50" : "opacity-85",
                        hover === i && "opacity-100 ring-2 ring-fg/60",
                      )}
                      style={{ left: `${(r.start / end) * 100}%`, width: `${(((r.end ?? r.start) - r.start) / end) * 100}%` }}
                    />
                  ),
                ),
              )}
            </div>
            <div className="mt-1 flex justify-between font-mono text-[11px] text-faint">
              <span>0 s</span>
              <span>video timeline</span>
              <span>{end.toFixed(0)} s</span>
            </div>
          </div>
        )}

        {issues.length === 0 ? (
          <p className="text-sm text-muted">Nothing to report.</p>
        ) : (
          <ul className="space-y-3">
            {issues.map((issue, i) => (
              <li
                key={i}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                className={clsx("rounded-md border border-line p-3 transition-colors", hover === i && "border-line-strong bg-panel-2")}
              >
                <div className={clsx("flex items-center gap-2 text-sm font-medium", SEVERITY[issue.severity].text)}>
                  {SEVERITY[issue.severity].icon}
                  {issue.title}
                </div>
                <p className="mt-1 text-sm text-fg">{issue.fix}</p>
                <p className="mt-1 text-xs text-muted">{issue.detail}</p>
                {issue.ranges.length > 0 && (
                  <div className="mt-2 flex gap-2 overflow-x-auto pb-1">
                    {issue.ranges.slice(0, 6).map((r, j) => (
                      <figure key={j} className="w-24 shrink-0">
                        <FrameThumb runId={run.id} name={r.first} version={run.stages[0].finished ?? ""} />
                        <figcaption className="mt-0.5 truncate font-mono text-[10px] text-faint">{when(r)}</figcaption>
                      </figure>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}

        {typeof sfm.retry === "string" && sfm.retry && (
          <p className="flex items-start gap-1.5 text-xs text-faint">
            <RotateCcw className="mt-0.5 size-3 shrink-0" />
            {sfm.retry}
          </p>
        )}
      </div>
    </Card>
  );
}

/** A frame's thumbnail: extracted frames live in frames/, extra ones from the camera-pose retry in sfm/images/. */
function FrameThumb({ runId, name, version }: { runId: string; name: string; version: string }) {
  const [src, setSrc] = useState(`${api.file(runId, `frames/${name}`)}?v=${encodeURIComponent(version)}`);
  return (
    <a href={src} target="_blank" rel="noreferrer">
      <img
        src={src}
        alt={name}
        loading="lazy"
        onError={() => !src.includes("sfm/images") && setSrc(api.file(runId, `sfm/images/${name}`))}
        className="h-20 w-full rounded bg-bg object-contain hover:opacity-80"
      />
    </a>
  );
}
