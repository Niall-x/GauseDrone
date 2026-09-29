import { AlertTriangle, Box, Eye, Layers } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, type Run } from "../api/client";
import { EmptyState, ErrorBanner, PageHeader, ProgressBar, Spinner, StatusBadge, stageWarnings } from "../components/ui";
import { formatDuration, timeAgo } from "../lib/format";
import { usePoll } from "../lib/hooks";

export function runProgress(run: Run): { value: number; label: string } {
  const n = run.stages.length;
  const done = run.stages.filter((s) => s.status === "done").length;
  const current = run.stages.find((s) => s.status === "running");
  const value = (done + (current?.progress ?? 0)) / n;
  return { value, label: current ? `${current.name}: ${current.message}` : `${done}/${n} stages` };
}

export function RunsPage() {
  // Poll fast only while something is queued or running; idle, a new run shows up within 10 s.
  const [busy, setBusy] = useState(true);
  const { data: runs, error } = usePoll(api.runs, busy ? 2000 : 10000);
  useEffect(() => setBusy(!runs || runs.some((r) => r.status === "queued" || r.status === "running")), [runs]);
  const { data: captures } = usePoll(api.captures, 10000);
  const captureName = (id: string) => captures?.find((c) => c.id === id)?.name ?? id;

  return (
    <>
      <PageHeader title="Runs" subtitle="Each run takes one capture through frames → camera poses → training → export." />
      <ErrorBanner error={error} className="mb-4" />
      {!runs && !error && <Spinner />}
      {runs?.length === 0 && (
        <EmptyState icon={<Layers className="size-8" />} title="No runs yet">
          Import a capture (a video or a folder of photos) on the{" "}
          <Link to="/captures" className="text-accent hover:underline">
            Captures
          </Link>{" "}
          page, then start a{" "}
          <Link to="/runs/new" className="text-accent hover:underline">
            new run
          </Link>
          .
        </EmptyState>
      )}
      {runs && runs.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-line">
          <table className="w-full table-fixed text-sm">
            <thead className="bg-panel text-left text-xs text-faint">
              <tr>
                <th className="px-4 py-2.5 font-medium">Run</th>
                <th className="w-32 px-4 py-2.5 font-medium">Status</th>
                <th className="w-[30%] px-4 py-2.5 font-medium">Progress</th>
                <th className="w-28 px-4 py-2.5 text-right font-medium">Quality</th>
                <th className="w-28 px-4 py-2.5 text-right font-medium">Created</th>
                <th className="w-12" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {runs.map((run) => {
                const p = runProgress(run);
                const train = run.stages.find((s) => s.name === "train")?.result as Record<string, number> | undefined;
                const sfm = run.stages.find((s) => s.name === "sfm")?.result as Record<string, number> | undefined;
                const psnr = train?.test_psnr ?? train?.train_psnr;
                const warnings = run.stages.flatMap((s) => (s.status === "done" ? stageWarnings(s) : []));
                return (
                  <tr key={run.id} className="bg-bg transition-colors hover:bg-panel">
                    <td className="px-4 py-3">
                      <div className="flex min-w-0 items-center gap-1.5">
                        <Link to={`/runs/${run.id}`} className="truncate font-medium hover:text-accent">
                          {run.name}
                        </Link>
                        {warnings.length > 0 && (
                          <span title={warnings.join("\n\n")} className="shrink-0 text-warn">
                            <AlertTriangle className="size-3.5" />
                          </span>
                        )}
                      </div>
                      <div className="truncate text-xs text-faint">
                        {captureName(run.capture_id)} · {String(run.config.train?.iterations ?? "?")} it
                        {sfm?.registered_frames != null && ` · ${sfm.registered_frames}/${sfm.total_frames} frames posed`}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-4 py-3">
                      <ProgressBar value={p.value} status={run.status} />
                      <div className="mt-1 truncate text-xs text-faint">
                        {run.status === "running" ? p.label : run.status === "done" && train?.train_seconds ? `trained in ${formatDuration(train.train_seconds)}` : p.label}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs tabular-nums text-muted">
                      {psnr != null ? (
                        <span title={train?.test_psnr != null ? "PSNR on held-out frames" : "PSNR on training frames"}>
                          {psnr.toFixed(2)} dB{train?.test_psnr == null && <span className="text-faint">*</span>}
                        </span>
                      ) : (
                        "–"
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-xs text-faint">{timeAgo(run.created)}</td>
                    <td className="px-2 py-3">
                      {run.stages.find((s) => s.name === "export")?.status === "done" ? (
                        <Link to={`/runs/${run.id}/view`} title="Open viewer" className="inline-flex rounded-md p-1.5 text-muted hover:bg-panel-2 hover:text-accent">
                          <Eye className="size-4" />
                        </Link>
                      ) : (
                        <span className="inline-flex p-1.5 text-line-strong">
                          <Box className="size-4" />
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
