// Thin typed wrapper over the FastAPI backend. Types come from the backend's
// OpenAPI schema (`npm run gen:api` after `python scripts/dump_openapi.py`),
// so a backend model change shows up here as a type error.
import type { components } from "./schema";

export type Run = components["schemas"]["Run"];
export type StageState = components["schemas"]["StageState"];
export type Capture = components["schemas"]["Capture"];
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

/** Upload with progress (fetch can't report upload progress). */
export function uploadCapture(
  name: string,
  files: File[],
  onProgress: (fraction: number) => void,
): Promise<Capture> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("name", name);
    for (const f of files) form.append("files", f, f.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/captures/upload");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
      else {
        let msg = xhr.statusText;
        try {
          msg = JSON.parse(xhr.responseText).detail ?? msg;
        } catch {
          /* ignore */
        }
        reject(new ApiError(xhr.status, msg));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network error"));
    xhr.send(form);
  });
}
