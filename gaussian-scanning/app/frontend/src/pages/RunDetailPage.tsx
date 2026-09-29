import clsx from "clsx";
import { ChevronRight, Copy, Download, Eye, RotateCcw, Square, Terminal, Trash2, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, type Run, type StageConfig, type StageDef, type StageState } from "../api/client";
import { LossChart } from "../components/LossChart";
import { StageParams, configFrom } from "../components/StageParams";
import { Button, Card, ErrorBanner, Field, PageHeader, ProgressBar, Select, Spinner, Stat, StatusBadge, StatusIcon, WarningList, stageWarnings } from "../components/ui";
import { elapsed, formatDuration, formatNumber, timeAgo } from "../lib/format";
import { usePoll } from "../lib/hooks";

const ACTIVE = ["queued", "running"];

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const [active, setActive] = useState(true);
  const { data: run, error, refresh } = usePoll(() => api.run(runId), 1500, active, [runId]);
  const { data: info } = usePoll(api.stages, 0, false);
  const { data: capture } = usePoll(() => (run ? api.capture(run.capture_id) : Promise.resolve(undefined)), 0, false, [run?.capture_id]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showRerun, setShowRerun] = useState(false);

  useEffect(() => setActive(!run || ACTIVE.includes(run.status)), [run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !run) return <ErrorBanner error={error} />;
  if (!run || !info) return <Spinner />;

  const act = async (fn: () => Promise<unknown>): Promise<boolean> => {
    setActionError(null);
    try {
      await fn();
      setActive(true);
      refresh();
      return true;
    } catch (e) {
      setActionError((e as Error).message);
      return false;
    }
  };

  const exported = run.stages.find((s) => s.name === "export")?.status === "done";
  const trainStage = run.stages.find((s) => s.name === "train");
  const isActive = ACTIVE.includes(run.status);
  const stageDefs = Object.fromEntries(info.stages.map((s) => [s.name, s]));
  const r = (name: string) => (run.stages.find((s) => s.name === name)?.result ?? {}) as Record<string, number | string>;
  const sfm = r("sfm");
  const train = r("train");
  const exp = r("export");

  return (
    <>
      <PageHeader
        title={run.name}
        subtitle={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <StatusBadge status={run.status} />
            <span>
              from{" "}
              <Link to="/captures" className="text-fg hover:text-accent">
                {capture?.name ?? run.capture_id}
              </Link>
            </span>
            <span>{timeAgo(run.created)}</span>
            {run.base_run_id && (
              <span>
                based on{" "}
                <Link to={`/runs/${run.base_run_id}`} className="text-fg hover:text-accent">
                  {run.base_run_id}
                </Link>
              </span>
            )}
          </span>
        }
        actions={
          <>
            {isActive && (
              <Button variant="danger" icon={<Square className="size-3.5" />} onClick={() => act(() => api.cancelRun(run.id))}>
                Cancel
              </Button>
            )}
            {!isActive && run.status !== "done" && (
              <Button icon={<RotateCcw className="size-4" />} onClick={() => act(() => api.resumeRun(run.id))}>
                Resume
              </Button>
            )}
            {!isActive && (
              <Button icon={<Wrench className="size-4" />} onClick={() => setShowRerun((v) => !v)}>
                Re-run…
              </Button>
            )}
            <Button icon={<Copy className="size-4" />} onClick={() => navigate(`/runs/new?base=${run.id}`)} disabled={run.stages[0].status !== "done"} title="New run reusing this run's frames/poses">
              New run from this
            </Button>
            {!isActive && (
              <Button
                variant="ghost"
                icon={<Trash2 className="size-4" />}
                title="Delete run"
                onClick={() => confirm(`Delete run "${run.name}" and all its outputs?`) && act(async () => { await api.deleteRun(run.id); navigate("/"); })}
              />
            )}
            {exported && (
              <Link to={`/runs/${run.id}/view`}>
                <Button variant="primary" icon={<Eye className="size-4" />}>
                  Open viewer
                </Button>
              </Link>
            )}
          </>
        }
      />
      <ErrorBanner error={actionError} className="mb-4" />

      {showRerun && <RerunPanel run={run} stages={info.stages} onClose={() => setShowRerun(false)} onSubmit={(from, cfg) => act(() => api.rerun(run.id, from, cfg)).then((ok) => ok && setShowRerun(false))} />}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Pipeline">
            <ol className="divide-y divide-line">
              {run.stages.map((s) => (
                <StageRow key={s.name} run={run} stage={s} def={stageDefs[s.name]} />
              ))}
            </ol>
          </Card>
          {/* Keyed on when the stage finished, so a re-run in place refetches instead of showing the old result. */}
          {trainStage?.status === "done" && <LossChart key={trainStage.finished ?? ""} url={api.file(run.id, "train/stats.json")} />}
          {run.stages[0].status === "done" && <FramesStrip key={run.stages[0].finished ?? ""} runId={run.id} version={run.stages[0].finished ?? ""} />}
        </div>

        <div className="space-y-4">
          <Card title="Summary">
            <div className="grid grid-cols-2 gap-x-4 gap-y-3 p-4">
              <Stat label="Frames posed" value={sfm.registered_frames != null ? `${sfm.registered_frames} / ${sfm.total_frames}` : null} />
              <Stat label="Sparse points" value={sfm.sparse_points != null ? formatNumber(Number(sfm.sparse_points)) : null} />
              <Stat label="Reprojection err." value={sfm.mean_reprojection_error_px != null ? `${sfm.mean_reprojection_error_px} px` : null} hint="Mean COLMAP reprojection error; under ~1 px is healthy" />
              <Stat label="Gaussians" value={train.num_gaussians != null ? formatNumber(Number(train.num_gaussians)) : null} />
              <Stat label="PSNR (held-out)" value={train.test_psnr != null ? `${train.test_psnr} dB` : null} hint="On frames excluded from training; enable with 'Hold out every Nth frame'" />
              <Stat label="SSIM (held-out)" value={train.test_ssim ?? null} />
              <Stat label="PSNR (train)" value={train.train_psnr != null ? `${train.train_psnr} dB` : null} hint="On training frames; optimistic" />
              <Stat label="Train time" value={train.train_seconds != null ? formatDuration(Number(train.train_seconds)) : null} />
              <Stat label="Peak GPU mem" value={train.peak_gpu_mem_gb != null ? `${train.peak_gpu_mem_gb} GB` : null} />
              <Stat label="SfM time" value={sfm.sfm_seconds != null ? formatDuration(Number(sfm.sfm_seconds)) : null} />
            </div>
          </Card>

          {exported && (
            <Card title="Downloads">
              <div className="flex flex-col gap-2 p-4 text-sm">
                <a className="inline-flex items-center gap-2 text-muted hover:text-accent" href={api.file(run.id, "export/splat.ply")} download={`${run.id}.ply`}>
                  <Download className="size-4" /> splat.ply <span className="text-faint">({exp.ply_mb} MB, full precision; opens in SuperSplat)</span>
                </a>
                <a className="inline-flex items-center gap-2 text-muted hover:text-accent" href={api.file(run.id, "export/splat.spz")} download={`${run.id}.spz`}>
                  <Download className="size-4" /> splat.spz <span className="text-faint">({exp.spz_mb} MB, compressed)</span>
                </a>
              </div>
            </Card>
          )}

          <Card title="Configuration">
            <dl className="space-y-3 p-4 text-xs">
              {Object.entries(run.config).map(([stage, values]) =>
                Object.keys(values).length ? (
                  <div key={stage}>
                    <dt className="mb-1 font-semibold text-muted">{stageDefs[stage]?.label ?? stage}</dt>
                    {Object.entries(values).map(([k, v]) => (
                      <dd key={k} className="flex justify-between gap-2 font-mono">
                        <span className="text-faint">{k}</span>
                        <span>{String(v)}</span>
                      </dd>
                    ))}
                  </div>
                ) : null,
              )}
            </dl>
          </Card>

          <Card title="Environment">
            <dl className="space-y-1 p-4 font-mono text-xs">
              {Object.entries(run.env).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3">
                  <dt className="text-faint">{k}</dt>
                  <dd className="truncate" title={String(v)}>
                    {String(v) || "–"}
                  </dd>
                </div>
              ))}
            </dl>
          </Card>
        </div>
      </div>
    </>
  );
}

function StageRow({ run, stage, def }: { run: Run; stage: StageState; def?: StageDef }) {
  const [showLog, setShowLog] = useState(false);
  const [, setTick] = useState(0);
  const running = stage.status === "running";
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [running]);
  const secs = elapsed(stage.started, stage.finished);
  const resultEntries = Object.entries(stage.result ?? {}).filter(([, v]) => typeof v !== "object");

  return (
    <li className="px-4 py-3">
      <div className="flex items-center gap-3">
        <StatusIcon status={stage.status} className="shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-sm font-medium">
              {def?.label ?? stage.name}
              {stage.reused_from && <span className="ml-2 text-xs font-normal text-faint">reused from {stage.reused_from}</span>}
            </span>
            <span className="shrink-0 font-mono text-xs tabular-nums text-faint">{secs != null && !stage.reused_from ? formatDuration(secs) : ""}</span>
          </div>
          <div className="truncate text-xs text-faint">{running || stage.status === "failed" ? stage.message || def?.description : def?.description}</div>
        </div>
        <button
          onClick={() => setShowLog((v) => !v)}
          disabled={stage.status === "pending" || !!stage.reused_from}
          className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-1 text-xs text-muted hover:bg-panel-2 hover:text-fg disabled:invisible"
        >
          <Terminal className="size-3.5" /> log
          <ChevronRight className={clsx("size-3 transition-transform", showLog && "rotate-90")} />
        </button>
      </div>
      {(running || (stage.status !== "done" && stage.progress > 0)) && <ProgressBar value={stage.progress} status={stage.status} className="ml-7 mt-2" />}
      {stage.error && <pre className="ml-7 mt-2 max-h-48 overflow-auto rounded border border-bad/30 bg-bad/5 p-2 font-mono text-[11px] leading-relaxed text-bad">{stage.error}</pre>}
      {stage.status === "done" && <WarningList warnings={stageWarnings(stage)} className="ml-7 mt-2" />}
      {stage.status === "done" && resultEntries.length > 0 && (
        <div className="ml-7 mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-faint">
          {resultEntries.map(([k, v]) => (
            <span key={k}>
              {k}=<span className="text-muted">{String(v)}</span>
            </span>
          ))}
        </div>
      )}
      {showLog && <LogView runId={run.id} stage={stage.name} live={running} />}
    </li>
  );
}

function LogView({ runId, stage, live }: { runId: string; stage: string; live: boolean }) {
  const { data } = usePoll(() => api.log(runId, stage, 400), 2000, live, [runId, stage]);
  return (
    <pre
      ref={(el) => {
        if (el && live) el.scrollTop = el.scrollHeight;
      }}
      className="ml-7 mt-2 max-h-80 overflow-auto rounded border border-line bg-bg p-2 font-mono text-[11px] leading-relaxed text-muted"
    >
      {data ?? "loading…"}
    </pre>
  );
}

function FramesStrip({ runId, version }: { runId: string; version: string }) {
  const { data: frames } = usePoll(() => api.frames(runId), 0, false, [runId]);
  // Frame file names repeat across re-runs; the version makes the thumbnails refetch.
  const src = (f: string) => `${api.file(runId, `frames/${f}`)}?v=${encodeURIComponent(version)}`;
  if (!frames?.length) return null;
  const step = Math.max(1, Math.floor(frames.length / 24));
  const sample = frames.filter((_, i) => i % step === 0).slice(0, 24);
  return (
    <Card title={`Frames (${frames.length})`}>
      <div className="grid grid-cols-4 gap-1.5 p-3 sm:grid-cols-6">
        {sample.map((f) => (
          <a key={f} href={src(f)} target="_blank" rel="noreferrer" title={f}>
            <img src={src(f)} loading="lazy" alt={f} className="aspect-video w-full rounded object-cover transition-opacity hover:opacity-80" />
          </a>
        ))}
      </div>
    </Card>
  );
}

function RerunPanel({
  run,
  stages,
  onClose,
  onSubmit,
}: {
  run: Run;
  stages: StageDef[];
  onClose: () => void;
  onSubmit: (from: string, config: StageConfig) => void;
}) {
  const [from, setFrom] = useState("train");
  const [config, setConfig] = useState<StageConfig>(() => configFrom(stages, run.config as StageConfig));
  const names = stages.map((s) => s.name);
  const locked = names.slice(0, names.indexOf(from));
  const firstIncomplete = run.stages.findIndex((s) => s.status !== "done");

  return (
    <Card title="Re-run this run in place" actions={<Button size="sm" variant="ghost" onClick={onClose}>Close</Button>} className="mb-4">
      <div className="space-y-4 p-4">
        <p className="text-sm text-muted">
          Replaces this run's outputs from the chosen stage onward. To keep the current result for comparison, use <em>New run from this</em> instead.
        </p>
        <Field label="Start from stage">
          <Select value={from} onChange={(e) => setFrom(e.target.value)} className="max-w-xs">
            {stages.map((s, i) => (
              <option key={s.name} value={s.name} disabled={firstIncomplete !== -1 && i > firstIncomplete}>
                {s.label}
              </option>
            ))}
          </Select>
        </Field>
        <StageParams
          stages={stages}
          config={config}
          disabledStages={locked}
          onChange={(stage, param, value) => setConfig((c) => ({ ...c, [stage]: { ...c[stage], [param]: value } }))}
        />
        <div className="flex justify-end">
          <Button
            variant="primary"
            icon={<RotateCcw className="size-4" />}
            onClick={() => {
              // Send the full values of the stages being re-run so reverting to a default also applies.
              const full: StageConfig = {};
              for (const s of names.slice(names.indexOf(from))) if (config[s] && Object.keys(config[s]).length) full[s] = config[s];
              onSubmit(from, full);
            }}
          >
            Re-run from {stages.find((s) => s.name === from)?.label}
          </Button>
        </div>
      </div>
    </Card>
  );
}
