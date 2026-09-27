import { useEffect, useState } from "react";
import { Card } from "./ui";

interface Stats {
  loss_curve: [number, number, number][]; // step, smoothed loss, gaussians
  iterations: number;
}

const W = 600;
const H = 140;
const PAD = { l: 44, r: 52, t: 10, b: 22 };

/** Training loss and Gaussian count over steps, from train/stats.json. */
export function LossChart({ url }: { url: string }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    fetch(url)
      .then((r) => (r.ok ? r.json() : null))
      .then(setStats)
      .catch(() => setStats(null));
  }, [url]);

  const pts = stats?.loss_curve ?? [];
  if (pts.length < 2) return null;

  const maxStep = pts[pts.length - 1][0] || 1;
  const losses = pts.map((p) => p[1]);
  const lo = Math.min(...losses);
  const hi = Math.max(...losses.slice(Math.min(3, losses.length - 1))); // skip the first few very high values
  const maxG = Math.max(...pts.map((p) => p[2]));
  const x = (s: number) => PAD.l + (s / maxStep) * (W - PAD.l - PAD.r);
  const yL = (v: number) => PAD.t + (1 - (Math.min(v, hi) - lo) / (hi - lo || 1)) * (H - PAD.t - PAD.b);
  const yG = (v: number) => PAD.t + (1 - v / (maxG || 1)) * (H - PAD.t - PAD.b);
  const line = (f: (p: [number, number, number]) => number) => pts.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${f(p).toFixed(1)}`).join("");
  const h = hover != null ? pts[hover] : null;

  return (
    <Card
      title="Training"
      actions={
        <div className="flex gap-3 text-xs text-faint">
          <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-3 bg-accent" /> loss</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-3 bg-warn" /> Gaussians</span>
        </div>
      }
    >
      <div className="relative p-3">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const step = ((e.clientX - r.left) / r.width * W - PAD.l) / (W - PAD.l - PAD.r) * maxStep;
            let best = 0;
            for (let i = 0; i < pts.length; i++) if (Math.abs(pts[i][0] - step) < Math.abs(pts[best][0] - step)) best = i;
            setHover(best);
          }}
          onMouseLeave={() => setHover(null)}
        >
          {[0, 0.5, 1].map((f) => (
            <line key={f} x1={PAD.l} x2={W - PAD.r} y1={PAD.t + f * (H - PAD.t - PAD.b)} y2={PAD.t + f * (H - PAD.t - PAD.b)} stroke="var(--color-line)" strokeWidth={1} />
          ))}
          <path d={line((p) => yG(p[2]))} fill="none" stroke="var(--color-warn)" strokeWidth={1.5} opacity={0.8} />
          <path d={line((p) => yL(p[1]))} fill="none" stroke="var(--color-accent)" strokeWidth={1.5} />
          <text x={PAD.l - 6} y={PAD.t + 4} textAnchor="end" className="fill-[var(--color-faint)] text-[10px]">{hi.toFixed(3)}</text>
          <text x={PAD.l - 6} y={H - PAD.b} textAnchor="end" className="fill-[var(--color-faint)] text-[10px]">{lo.toFixed(3)}</text>
          <text x={W - PAD.r + 6} y={PAD.t + 4} className="fill-[var(--color-faint)] text-[10px]">{(maxG / 1e6).toFixed(2)}M</text>
          <text x={W - PAD.r} y={H - 6} textAnchor="end" className="fill-[var(--color-faint)] text-[10px]">{maxStep.toLocaleString()} steps</text>
          {h && (
            <>
              <line x1={x(h[0])} x2={x(h[0])} y1={PAD.t} y2={H - PAD.b} stroke="var(--color-muted)" strokeDasharray="2 3" />
              <circle cx={x(h[0])} cy={yL(h[1])} r={3} fill="var(--color-accent)" />
              <circle cx={x(h[0])} cy={yG(h[2])} r={3} fill="var(--color-warn)" />
            </>
          )}
        </svg>
        {h && (
          <div className="pointer-events-none absolute right-4 top-3 rounded border border-line bg-panel-2 px-2 py-1 font-mono text-[11px] text-muted">
            step {h[0].toLocaleString()} · loss {h[1].toFixed(4)} · {h[2].toLocaleString()} Gaussians
          </div>
        )}
      </div>
    </Card>
  );
}
