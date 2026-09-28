// Thin typed wrapper over the FastAPI backend. Types come from the backend's
// OpenAPI schema (`npm run gen:api` after `python scripts/dump_openapi.py`),
// so a backend model change shows up here as a type error.
import type { components } from "./schema";

export type Run = components["schemas"]["Run"];
export type StageState = components["schemas"]["StageState"];
export type Capture = components["schemas"]["Capture"];
export type Upload = components["schemas"]["Upload"];
export type UploadItem = components["schemas"]["UploadItem"];
export type RunStatus = Run["status"];
export type StageStatus = StageState["status"];
export type StageConfig = Record<string, Record<string, unknown>>;

export interface ParamDef {
  name: string;
  label: string;
  type: "int" | "float" | "choice";
  default: number | string;
  help: string;
  choices: (number | string)[] | null;
  min: number | null;
  max: number | null;
}

export interface StageDef {
  name: string;
  label: string;
  module: string;
  description: string;
  outputs: string[];
  params: ParamDef[];
  needs_input: boolean;
}

export interface Preset {
  label: string;
  description: string;
  config: StageConfig;
}

export interface StagesInfo {
  stages: StageDef[];
  presets: Record<string, Preset>;
}

export interface SystemInfo {
  git_commit: string;
  colmap: string;
  torch: string;
  gsplat: string;
  gpu: string;
  data_dir: string;
  disk_free_gb: number;
  gpu_mem_used_mb: number | null;
  gpu_mem_total_mb: number | null;
  active_run: string | null;
  queued_runs: string[];
}

export class ApiError extends Error {
  /** On a 409 from an upload chunk: how many bytes of that file the server actually has. */
  received?: number;

  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  system: () => request<SystemInfo>("/system"),
  stages: () => request<StagesInfo>("/stages"),

  captures: () => request<Capture[]>("/captures"),
  capture: (id: string) => request<Capture>(`/captures/${id}`),
  importCapture: (body: { path: string; name?: string; link?: boolean }) =>
    request<Capture>("/captures/import", json("POST", body)),
  updateCapture: (id: string, body: { name?: string; notes?: string }) =>
    request<Capture>(`/captures/${id}`, json("PATCH", body)),
  deleteCapture: (id: string) => request<unknown>(`/captures/${id}`, { method: "DELETE" }),
  captureThumb: (id: string) => `/api/captures/${id}/thumb`,

  runs: () => request<Run[]>("/runs"),
  run: (id: string) => request<Run>(`/runs/${id}`),
  createRun: (body: {
    capture_id: string;
    name?: string;
    preset?: string;
    config?: StageConfig;
    base_run_id?: string;
    reuse_until?: string;
  }) => request<Run>("/runs", json("POST", body)),
  updateRun: (id: string, body: { name?: string; notes?: string }) =>
    request<Run>(`/runs/${id}`, json("PATCH", body)),
  cancelRun: (id: string) => request<Run>(`/runs/${id}/cancel`, { method: "POST" }),
  resumeRun: (id: string) => request<Run>(`/runs/${id}/resume`, { method: "POST" }),
  rerun: (id: string, from_stage: string, config?: StageConfig) =>
    request<Run>(`/runs/${id}/rerun`, json("POST", { from_stage, config })),
  deleteRun: (id: string) => request<unknown>(`/runs/${id}`, { method: "DELETE" }),
  log: (id: string, stage: string, tail = 300) => request<string>(`/runs/${id}/log/${stage}?tail=${tail}`),
  frames: (id: string) => request<string[]>(`/runs/${id}/frames`),
  file: (id: string, path: string) => `/api/runs/${id}/files/${path}`,
};

// --- resumable uploads: each file goes up in chunks appended at an explicit
// offset, so a dropped connection or server restart only costs the chunk in flight ---

const CHUNK_BYTES = 16 << 20;
const PARALLEL_FILES = 4; // many small photos: hide per-request latency (e.g. over Tailscale)
const MAX_RETRIES = 8; // per chunk, with backoff up to 30 s (~3 min of outage)

const sourceOf = (f: File) => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
const fileKey = (source: string, size: number) => `${source}\u0000${size}`;

export const listUploads = () => request<Upload[]>("/uploads");
export const discardUpload = (id: string) => request<unknown>(`/uploads/${id}`, { method: "DELETE" });

/** An unfinished upload of exactly these files (same names and sizes), which picking them again resumes. */
export async function findResumable(files: File[]): Promise<Upload | undefined> {
  const want = files.map((f) => fileKey(sourceOf(f), f.size)).sort().join("\n");
  return (await listUploads()).find((u) => u.files.map((f) => fileKey(f.source, f.size)).sort().join("\n") === want);
}

function putChunk(uploadId: string, index: number, offset: number, chunk: Blob, onLoaded: (bytes: number) => void): Promise<UploadItem> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/uploads/${uploadId}/files/${index}?offset=${offset}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => onLoaded(e.loaded);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) return resolve(JSON.parse(xhr.responseText));
      let detail: unknown = xhr.statusText;
      try {
        detail = JSON.parse(xhr.responseText).detail;
      } catch {
        /* not JSON */
      }
      const d = detail as { message?: string; received?: number } | string;
      const err = new ApiError(xhr.status, typeof d === "string" ? d : (d.message ?? xhr.statusText));
      if (typeof d === "object" && d.received != null) err.received = d.received;
      reject(err);
    };
    xhr.onerror = () => reject(new ApiError(0, "network error"));
    xhr.send(chunk);
  });
}

/** Upload files as a new capture, or continue `resume` (from findResumable) where the server left off. */
export async function uploadFiles(
  name: string,
  files: File[],
  onProgress: (fraction: number) => void,
  resume?: Upload,
): Promise<Capture> {
  const up =
    resume ?? (await request<Upload>("/uploads", json("POST", { name, files: files.map((f) => ({ source: sourceOf(f), size: f.size })) })));

  const byKey = new Map<string, File[]>();
  for (const f of files) byKey.set(fileKey(sourceOf(f), f.size), [...(byKey.get(fileKey(sourceOf(f), f.size)) ?? []), f]);
  const jobs = up.files.map((item, index) => ({ item, index, file: byKey.get(fileKey(item.source, item.size))!.shift()! }));

  const total = jobs.reduce((a, j) => a + j.item.size, 0);
  const sent = jobs.map((j) => j.item.received);
  const report = () => onProgress(total ? sent.reduce((a, b) => a + b, 0) / total : 1);
  report();

  let stopped: Error | null = null;
  const sendFile = async ({ item, index, file }: (typeof jobs)[number]) => {
    let offset = item.received;
    let failures = 0;
    while (offset < item.size && !stopped) {
      const start = offset;
      try {
        const chunk = file.slice(start, Math.min(start + CHUNK_BYTES, item.size));
        offset = (await putChunk(up.id, index, start, chunk, (n) => ((sent[index] = start + n), report()))).received;
        failures = 0;
      } catch (e) {
        const err = e as ApiError;
        if (err.status === 409 && err.received != null) offset = err.received; // e.g. a retried chunk that had landed
        else if (err.status >= 400 && err.status < 500) throw err; // won't succeed on retry
        else {
          if (++failures > MAX_RETRIES) throw new ApiError(err.status, `upload interrupted (${err.message}); press Upload again with the same files to resume`);
          await new Promise((r) => setTimeout(r, Math.min(30_000, 1000 * 2 ** (failures - 1))));
          try {
            offset = (await request<Upload>(`/uploads/${up.id}`)).files[index].received; // did the chunk land?
          } catch {
            /* server still unreachable; the next attempt retries */
          }
        }
      }
      sent[index] = offset;
      report();
    }
  };

  const queue = jobs.filter((j) => j.item.received < j.item.size);
  await Promise.all(
    Array.from({ length: Math.min(PARALLEL_FILES, queue.length) }, async () => {
      while (queue.length && !stopped) {
        try {
          await sendFile(queue.shift()!);
        } catch (e) {
          stopped ??= e as Error;
        }
      }
    }),
  );
  if (stopped) throw stopped;
  return request<Capture>(`/uploads/${up.id}/finish`, { method: "POST" });
}
