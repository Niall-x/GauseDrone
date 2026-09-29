import clsx from "clsx";
import { ArrowLeft, Camera, ChevronLeft, ChevronRight, Download, Home, Image as ImageIcon, Keyboard, Map as MapIcon, MousePointer2, Route, Scissors, Video } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";
import { api } from "../api/client";
import { ErrorBanner, Spinner } from "../components/ui";
import { usePoll } from "../lib/hooks";
import { SplatViewer, type SplatViewerHandle, type ViewInfo, type ViewerStats } from "../viewer/SplatViewer";

// Mouse sensitivity is a per-browser preference, kept across runs and reloads.
const SENSITIVITY_KEY = "viewer.sensitivity";
type Sensitivity = { look: number; scroll: number };
const DEFAULT_SENSITIVITY: Sensitivity = { look: 1, scroll: 1 };

function loadSensitivity(): Sensitivity {
  try {
    const v = JSON.parse(localStorage.getItem(SENSITIVITY_KEY) ?? "null");
    const ok = (x: unknown) => typeof x === "number" && x >= 0.1 && x <= 10;
    if (v && ok(v.look) && ok(v.scroll)) return { look: v.look, scroll: v.scroll };
  } catch {
    // storage blocked or corrupt: fall back to defaults
  }
  return DEFAULT_SENSITIVITY;
}

export function ViewerPage() {
  const { runId = "" } = useParams();
  const { data: run, error: runError } = usePoll(() => api.run(runId), 0, false, [runId]);
  const [view, setView] = useState<ViewInfo | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(0);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [stats, setStats] = useState<ViewerStats | null>(null);
  const [showTrajectory, setShowTrajectory] = useState(false);
  const [showFrustums, setShowFrustums] = useState(false);
  const [showPhoto, setShowPhoto] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [camIndex, setCamIndex] = useState<number | null>(null);
  const [cutaway, setCutaway] = useState<number | null>(null);
  const [showMouse, setShowMouse] = useState(false);
  const [sensitivity, setSensitivity] = useState(loadSensitivity);
  const viewer = useRef<SplatViewerHandle>(null);

  useEffect(() => {
    fetch(api.file(runId, "export/view.json"))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`view.json: ${r.status}`))))
      .then(setView)
      .catch((e) => setViewError(String(e.message ?? e)));
  }, [runId]);

  useEffect(() => {
    try {
      localStorage.setItem(SENSITIVITY_KEY, JSON.stringify(sensitivity));
    } catch {
      // not persisted; the setting still applies for this visit
    }
  }, [sensitivity]);

  const goTo = (i: number) => {
    if (!view) return;
    const n = view.cameras.length;
    const idx = ((i % n) + n) % n;
    setCamIndex(idx);
    viewer.current?.goToCamera(idx);
  };

  // Keyboard: [ and ] step through capture cameras, R resets.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLInputElement | null;
      if ((t?.tagName === "INPUT" && t.type !== "range") || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "]") goTo((camIndex ?? -1) + 1);
      else if (e.key === "[") goTo((camIndex ?? 1) - 1);
      else if (e.key === "r") {
        setCamIndex(null);
        viewer.current?.resetView();
      } else if (e.key === "o") {
        setCamIndex(null);
        setShowTrajectory(true);
        setCutaway((c) => c ?? 0.6);
        viewer.current?.overview();
      } else if (e.key === "?") setShowHelp((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const screenshot = async () => {
    const blob = await viewer.current?.screenshot();
    if (!blob) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${runId}-${Date.now()}.png`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const error = runError?.message ?? viewError ?? loadError;
  const cam = camIndex != null ? view?.cameras[camIndex] : null;

  return (
    <div className="fixed inset-0 overflow-hidden bg-bg">
      {view && (
        <SplatViewer
          ref={viewer}
          url={api.file(runId, "export/splat.spz")}
          view={view}
          showTrajectory={showTrajectory}
          showFrustums={showFrustums}
          cutaway={cutaway}
          lookSensitivity={sensitivity.look}
          scrollSensitivity={sensitivity.scroll}
          onProgress={setProgress}
          onLoaded={() => setLoaded(true)}
          onError={setLoadError}
          onStats={setStats}
        />
      )}

      {/* top bar */}
      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-3 p-3">
        <div className="pointer-events-auto flex items-center gap-2 rounded-lg border border-line bg-panel/85 py-1.5 pl-1.5 pr-3 backdrop-blur">
          <Link to={`/runs/${runId}`} className="rounded-md p-1.5 text-muted hover:bg-panel-2 hover:text-fg" title="Back to run">
            <ArrowLeft className="size-4" />
          </Link>
          <div className="min-w-0">
            <div className="max-w-[40vw] truncate text-sm font-medium">{run?.name ?? runId}</div>
            {stats && (
              <div className="font-mono text-[11px] text-faint">
                {stats.splats.toLocaleString()} splats · {stats.fps.toFixed(0)} fps
              </div>
            )}
          </div>
        </div>

        <div className="pointer-events-auto flex items-center gap-1 rounded-lg border border-line bg-panel/85 p-1 backdrop-blur">
          <ToolButton active={showTrajectory} onClick={() => setShowTrajectory((v) => !v)} title="Capture path">
            <Route className="size-4" />
          </ToolButton>
          <ToolButton active={showFrustums} onClick={() => setShowFrustums((v) => !v)} title="Camera frustums">
            <Video className="size-4" />
          </ToolButton>
          <ToolButton active={cutaway != null} onClick={() => setCutaway((c) => (c == null ? 0.6 : null))} title="Cutaway: hide the ceiling and upper walls to see into the room from above">
            <Scissors className="size-4" />
          </ToolButton>
          <ToolButton active={showPhoto} onClick={() => setShowPhoto((v) => !v)} title="Show the source photo when snapped to a capture camera">
            <ImageIcon className="size-4" />
          </ToolButton>
          <Divider />
          <ToolButton
            onClick={() => {
              setCamIndex(null);
              setShowTrajectory(true);
              setCutaway((c) => c ?? 0.6);
              viewer.current?.overview();
            }}
            title="Overview: whole scene from above, with the capture path (O)"
          >
            <MapIcon className="size-4" />
          </ToolButton>
          <ToolButton onClick={() => { setCamIndex(null); viewer.current?.resetView(); }} title="Reset view (R)">
            <Home className="size-4" />
          </ToolButton>
          <ToolButton onClick={screenshot} title="Save screenshot">
            <Camera className="size-4" />
          </ToolButton>
          <a href={api.file(runId, "export/splat.ply")} download={`${runId}.ply`} className="rounded-md p-2 text-muted hover:bg-panel-2 hover:text-fg" title="Download PLY">
            <Download className="size-4" />
          </a>
          <ToolButton active={showMouse} onClick={() => setShowMouse((v) => !v)} title="Mouse sensitivity">
            <MousePointer2 className="size-4" />
          </ToolButton>
          <ToolButton active={showHelp} onClick={() => setShowHelp((v) => !v)} title="Controls (?)">
            <Keyboard className="size-4" />
          </ToolButton>
        </div>
      </div>

      {/* loading */}
      {!loaded && !error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
          <Spinner className="size-6" />
          <div className="text-sm text-muted">{progress != null && progress > 0 && progress < 1 ? `Loading splat… ${Math.round(progress * 100)}%` : "Loading splat…"}</div>
          {progress != null && progress > 0 && (
            <div className="h-1 w-48 overflow-hidden rounded-full bg-line">
              <div className="h-full bg-accent transition-[width]" style={{ width: `${progress * 100}%` }} />
            </div>
          )}
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center p-6">
          <ErrorBanner error={`Could not load this splat: ${error}`} className="max-w-lg" />
        </div>
      )}

      {/* camera stepper */}
      {view && loaded && (
        <div className="absolute inset-x-0 bottom-0 flex flex-col items-center gap-2 p-3">
          {showPhoto && cam && (
            <img
              src={api.file(runId, `frames/${cam.name}`)}
              alt={cam.name}
              className="max-h-[28vh] max-w-[40vw] rounded-md border border-line-strong object-contain shadow-2xl"
            />
          )}
          <div className="flex w-full max-w-xl items-center gap-2 rounded-lg border border-line bg-panel/85 px-2 py-1.5 backdrop-blur">
            <ToolButton onClick={() => goTo((camIndex ?? 1) - 1)} title="Previous capture camera ([)">
              <ChevronLeft className="size-4" />
            </ToolButton>
            <input
              type="range"
              min={0}
              max={view.cameras.length - 1}
              value={camIndex ?? 0}
              onChange={(e) => goTo(Number(e.target.value))}
              className="flex-1 accent-[var(--color-accent)]"
              aria-label="Capture camera"
            />
            <ToolButton onClick={() => goTo((camIndex ?? -1) + 1)} title="Next capture camera (])">
              <ChevronRight className="size-4" />
            </ToolButton>
            <span className="w-40 truncate text-right font-mono text-[11px] text-faint" title={cam?.name}>
              {cam ? `${camIndex! + 1}/${view.cameras.length} ${cam.name}` : `${view.cameras.length} capture cameras`}
            </span>
          </div>
        </div>
      )}

      {/* right-hand panels, stacked so they never overlap */}
      <div className="pointer-events-none absolute right-3 top-16 flex flex-col items-end gap-2 [&>*]:pointer-events-auto">
        {cutaway != null && (
          <div className="flex items-center gap-3 rounded-lg border border-line bg-panel/85 px-3 py-2 text-xs text-muted backdrop-blur">
            <Scissors className="size-3.5" />
            <span>Cut height</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={cutaway}
              onChange={(e) => setCutaway(Number(e.target.value))}
              className="w-40 accent-[var(--color-accent)]"
              aria-label="Cutaway height"
            />
            <span className="w-8 text-right font-mono">{Math.round(cutaway * 100)}%</span>
          </div>
        )}

        {showMouse && (
          <div className="w-72 rounded-lg border border-line bg-panel/95 p-4 text-xs text-muted backdrop-blur">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-fg">Mouse sensitivity</h3>
              <button
                onClick={() => setSensitivity(DEFAULT_SENSITIVITY)}
                disabled={sensitivity.look === 1 && sensitivity.scroll === 1}
                className="rounded px-1.5 py-0.5 text-muted hover:bg-panel-2 hover:text-fg disabled:invisible"
              >
                Reset
              </button>
            </div>
            <SensitivitySlider label="Look / orbit" value={sensitivity.look} onChange={(look) => setSensitivity((s) => ({ ...s, look }))} />
            <SensitivitySlider label="Scroll" value={sensitivity.scroll} onChange={(scroll) => setSensitivity((s) => ({ ...s, scroll }))} />
          </div>
        )}

        {showHelp && (
          <div className="w-72 rounded-lg border border-line bg-panel/95 p-4 text-xs text-muted backdrop-blur">
            <h3 className="mb-2 text-sm font-semibold text-fg">Controls</h3>
            <HelpRow k="Move">W A S D / arrows · E or Space up · Q or C down · Shift faster · scroll forward/back</HelpRow>
            <HelpRow k="Mouse">drag look around · right-drag orbit · middle-drag pan · double-click a surface to orbit it · sensitivity under the mouse-pointer button</HelpRow>
            <HelpRow k="[ ]">step through the capture cameras</HelpRow>
            <HelpRow k="O">overview from above, with the capture path and a cutaway</HelpRow>
            <HelpRow k="R">reset view</HelpRow>
            <p className="mt-3 text-faint">"Up" is estimated from the capture cameras, so a scan filmed mostly tilted may appear slightly skewed.</p>
          </div>
        )}
      </div>
    </div>
  );
}

function ToolButton({ active, children, ...rest }: { active?: boolean; children: ReactNode; onClick?: () => void; title?: string }) {
  return (
    <button {...rest} className={clsx("rounded-md p-2 transition-colors", active ? "bg-accent/15 text-accent" : "text-muted hover:bg-panel-2 hover:text-fg")}>
      {children}
    </button>
  );
}

/** 0.25x-4x on a log scale, so each end is as far from 1x as the other. */
function SensitivitySlider({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="mb-2 flex items-center gap-3 last:mb-0">
      <span className="w-20 shrink-0">{label}</span>
      <input
        type="range"
        min={-2}
        max={2}
        step={0.05}
        value={Math.log2(value)}
        onChange={(e) => onChange(Math.round(2 ** Number(e.target.value) * 100) / 100)}
        onDoubleClick={() => onChange(1)}
        className="min-w-0 flex-1 accent-[var(--color-accent)]"
        aria-label={`${label} sensitivity`}
      />
      <span className="w-10 text-right font-mono">{value.toFixed(2)}x</span>
    </label>
  );
}

function Divider() {
  return <span className="mx-0.5 h-5 w-px bg-line" />;
}

function HelpRow({ k, children }: { k: string; children: ReactNode }) {
  return (
    <div className="mb-1.5 flex gap-3">
      <span className="w-12 shrink-0 font-mono text-fg">{k}</span>
      <span>{children}</span>
    </div>
  );
}
