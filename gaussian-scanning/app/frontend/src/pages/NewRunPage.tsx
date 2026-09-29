import clsx from "clsx";
import { ChevronDown, Film, Image as ImageIcon, Play, Recycle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, type StageConfig } from "../api/client";
import { StageParams, configFrom, diffFromDefaults } from "../components/StageParams";
import { Button, Card, EmptyState, ErrorBanner, Field, Input, PageHeader, Select, Spinner } from "../components/ui";
import { formatDuration } from "../lib/format";
import { usePoll } from "../lib/hooks";

export function NewRunPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { data: captures } = usePoll(api.captures, 0, false);
  const { data: info } = usePoll(api.stages, 0, false);
  const { data: runs } = usePoll(api.runs, 0, false);

  const baseRunId = params.get("base");
  const baseRun = runs?.find((r) => r.id === baseRunId);

  const [captureId, setCaptureId] = useState(params.get("capture") ?? "");
  const [name, setName] = useState("");
  const [preset, setPreset] = useState("standard");
  const [reuseUntil, setReuseUntil] = useState<string>("sfm");
  const [config, setConfig] = useState<StageConfig>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (baseRun) setCaptureId(baseRun.capture_id);
    else if (!captureId && captures?.length) setCaptureId(captures[0].id);
  }, [baseRun, captures, captureId]);

  // Reuse as much as the base run finished (up to camera poses): the server refuses to reuse unfinished stages.
  useEffect(() => {
    if (!baseRun || !info) return;
    let last = "";
    for (const s of info.stages.slice(0, -1)) {
      if (baseRun.stages.find((x) => x.name === s.name)?.status !== "done") break;
      last = s.name;
      if (s.name === "sfm") break;
    }
    if (last) setReuseUntil(last);
  }, [baseRun, info]);

  // Settings = defaults <- (base run, if reusing) <- preset. Rebuilt when those change.
  useEffect(() => {
    if (!info) return;
    setConfig(configFrom(info.stages, baseRun?.config as StageConfig | undefined, info.presets[preset]?.config));
  }, [info, preset, baseRun]);

  const stageNames = info?.stages.map((s) => s.name) ?? [];
  const reusedStages = baseRun ? stageNames.slice(0, stageNames.indexOf(reuseUntil) + 1) : [];
  const capture = captures?.find((c) => c.id === captureId);
  const estimate = useMemo(() => {
    if (!capture) return null;
    const fps = Number(config.frames?.fps ?? 4);
    const frames = capture.kind === "video" ? Math.round((capture.duration_sec ?? 0) * fps) : capture.num_images;
    return frames;
  }, [capture, config]);

  if (!captures || !info) return <Spinner />;
  if (captures.length === 0)
    return (
      <>
        <PageHeader title="New run" />
        <EmptyState title="No captures to run">
          Add one on the{" "}
          <Link to="/captures" className="text-accent hover:underline">
            Captures
          </Link>{" "}
          page first.
        </EmptyState>
      </>
    );

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const run = await api.createRun({
        capture_id: captureId,
        name: name.trim() || undefined,
        config: diffFromDefaults(info.stages, config),
        base_run_id: baseRun?.id,
        reuse_until: baseRun ? reuseUntil : undefined,
      });
      navigate(`/runs/${run.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader title="New run" subtitle="Frames → camera poses (COLMAP) → Gaussian splat training (gsplat) → export for the viewer." />
      <div className="space-y-4">
        {baseRun && (
          <Card title={<span className="inline-flex items-center gap-2"><Recycle className="size-4 text-accent" /> Reusing results from “{baseRun.name}”</span>}>
            <div className="grid gap-4 p-4 sm:grid-cols-2">
              <Field label="Reuse stages up to and including" help="Reused outputs are hard-linked, so they take no extra disk space. The base run is left untouched.">
                <Select value={reuseUntil} onChange={(e) => setReuseUntil(e.target.value)}>
                  {info.stages.slice(0, -1).map((s) => (
                    <option key={s.name} value={s.name} disabled={baseRun.stages.find((x) => x.name === s.name)?.status !== "done"}>
                      {s.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
          </Card>
        )}

        <Card title="Capture">
          <div className="grid gap-2 p-4 sm:grid-cols-2 lg:grid-cols-3">
            {captures.map((c) => (
              <button
                key={c.id}
                disabled={!!baseRun && c.id !== baseRun.capture_id}
                onClick={() => setCaptureId(c.id)}
                className={clsx(
                  "flex items-center gap-3 rounded-md border p-2 text-left transition-colors disabled:opacity-30",
                  c.id === captureId ? "border-accent bg-accent/5" : "border-line hover:border-line-strong",
                )}
              >
                <img src={api.captureThumb(c.id)} alt="" className="h-12 w-20 shrink-0 rounded object-cover" />
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{c.name}</div>
                  <div className="flex items-center gap-1 text-xs text-faint">
                    {c.kind === "video" ? <Film className="size-3" /> : <ImageIcon className="size-3" />}
                    {c.kind === "video" ? formatDuration(c.duration_sec ?? 0) : `${c.num_images} photos`}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </Card>

        <Card title="Settings">
          <div className="space-y-4 p-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Run name">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={capture?.name ?? ""} />
              </Field>
              <Field label="Quality">
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(info.presets).map(([key, p]) => (
                    <button
                      key={key}
                      onClick={() => setPreset(key)}
                      className={clsx(
                        "rounded-md border px-3 py-1.5 text-left transition-colors",
                        preset === key ? "border-accent bg-accent/5" : "border-line hover:border-line-strong",
                      )}
                    >
                      <div className="text-sm font-medium">{p.label}</div>
                      <div className="text-xs text-faint">{p.description}</div>
                    </button>
                  ))}
                </div>
              </Field>
            </div>
            {estimate != null && !baseRun && (
              <p className="text-xs text-faint">
                ≈ {estimate} frames. Camera poses take a minute or two for a few hundred frames.
              </p>
            )}

            <button onClick={() => setShowAdvanced((v) => !v)} className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
              <ChevronDown className={clsx("size-4 transition-transform", showAdvanced && "rotate-180")} />
              Advanced settings
            </button>
            {showAdvanced && (
              <div className="rounded-md border border-line bg-bg p-4">
                <StageParams
                  stages={info.stages}
                  config={config}
                  disabledStages={reusedStages}
                  onChange={(stage, param, value) => setConfig((c) => ({ ...c, [stage]: { ...c[stage], [param]: value } }))}
                />
              </div>
            )}
          </div>
        </Card>

        <ErrorBanner error={error} />
        <div className="flex justify-end">
          <Button variant="primary" icon={<Play className="size-4" />} loading={busy} disabled={!captureId} onClick={submit}>
            Start run
          </Button>
        </div>
      </div>
    </>
  );
}
