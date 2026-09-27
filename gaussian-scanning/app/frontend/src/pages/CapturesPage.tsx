import { Film, FolderOpen, Image as ImageIcon, Link2, Play, Trash2, Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router";
import { api, uploadCapture, type Capture } from "../api/client";
import { Button, Card, EmptyState, ErrorBanner, Field, Input, PageHeader, ProgressBar, Spinner } from "../components/ui";
import { formatBytes, formatDuration, timeAgo } from "../lib/format";
import { usePoll } from "../lib/hooks";

const MEDIA = /\.(jpe?g|png|tiff?|bmp|webp|mp4|mov|m4v|avi|mkv|webm)$/i;

export function CapturesPage() {
  const { data: captures, error, refresh } = usePoll(api.captures, 10000);
  const [actionError, setActionError] = useState<string | null>(null);

  const remove = async (c: Capture) => {
    if (!confirm(`Delete capture "${c.name}"?${c.linked ? " (the linked original files are kept)" : ""}`)) return;
    try {
      await api.deleteCapture(c.id);
      refresh();
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  return (
    <>
      <PageHeader
        title="Captures"
        subtitle="Raw input: one video, or a set of photos, of one scene. Drone recordings will land here too."
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <UploadCard onDone={refresh} />
        <ImportCard onDone={refresh} />
      </div>
      <ErrorBanner error={error ?? actionError} className="mt-4" />
      <h2 className="mb-3 mt-8 text-sm font-semibold text-muted">Library</h2>
      {!captures && !error && <Spinner />}
      {captures?.length === 0 && <EmptyState icon={<FolderOpen className="size-8" />} title="No captures yet" />}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {captures?.map((c) => (
          <CaptureCard key={c.id} capture={c} onDelete={() => remove(c)} />
        ))}
      </div>
    </>
  );
}

function CaptureCard({ capture: c, onDelete }: { capture: Capture; onDelete: () => void }) {
  const navigate = useNavigate();
  return (
    <div className="group overflow-hidden rounded-lg border border-line bg-panel">
      <div className="relative aspect-video bg-panel-2">
        <img src={api.captureThumb(c.id)} alt="" className="size-full object-cover" onError={(e) => (e.currentTarget.style.display = "none")} />
        <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded bg-bg/80 px-1.5 py-0.5 text-[11px] text-muted backdrop-blur">
          {c.kind === "video" ? <Film className="size-3" /> : <ImageIcon className="size-3" />}
          {c.kind === "video" ? formatDuration(c.duration_sec ?? 0) : `${c.num_images} photos`}
        </span>
        {c.linked && (
          <span className="absolute right-2 top-2 inline-flex items-center gap-1 rounded bg-bg/80 px-1.5 py-0.5 text-[11px] text-muted backdrop-blur" title={c.origin}>
            <Link2 className="size-3" /> linked
          </span>
        )}
      </div>
      <div className="flex items-start justify-between gap-2 p-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium" title={c.name}>
            {c.name}
          </div>
          <div className="truncate text-xs text-faint">
            {c.resolution ? `${c.resolution[0]}×${c.resolution[1]} · ` : ""}
            {formatBytes(c.size_bytes)} · {timeAgo(c.created)}
          </div>
        </div>
        <div className="flex shrink-0 gap-1">
          <Button size="sm" variant="ghost" onClick={onDelete} title="Delete capture" icon={<Trash2 className="size-3.5" />} />
          <Button size="sm" variant="secondary" icon={<Play className="size-3.5" />} onClick={() => navigate(`/runs/new?capture=${c.id}`)}>
            Run
          </Button>
        </div>
      </div>
    </div>
  );
}

function UploadCard({ onDone }: { onDone: () => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  const pick = (list: FileList | null) => {
    const picked = Array.from(list ?? []).filter((f) => MEDIA.test(f.name));
    setFiles(picked);
    setError(picked.length ? null : "No images or videos in that selection");
    if (picked.length && !name) {
      const rel = (picked[0] as File & { webkitRelativePath?: string }).webkitRelativePath;
      setName(rel ? rel.split("/")[0] : picked[0].name.replace(/\.[^.]+$/, ""));
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    pick(e.dataTransfer.files);
  };

  const total = files.reduce((a, f) => a + f.size, 0);

  const submit = async () => {
    setError(null);
    setProgress(0);
    try {
      await uploadCapture(name || "capture", files, setProgress);
      setFiles([]);
      setName("");
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setProgress(null);
    }
  };

  return (
    <Card title="Upload from this computer">
      <div className="space-y-3 p-4">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center gap-2 rounded-md border border-dashed px-4 py-6 text-center text-sm transition-colors ${drag ? "border-accent bg-accent/5" : "border-line-strong"}`}
        >
          <Upload className="size-5 text-faint" />
          {files.length ? (
            <span>
              {files.length} file{files.length > 1 && "s"} · {formatBytes(total)}
            </span>
          ) : (
            <span className="text-muted">Drop a video or photos here</span>
          )}
          <div className="flex gap-2">
            <Button size="sm" onClick={() => fileInput.current?.click()}>
              Choose files
            </Button>
            <Button size="sm" onClick={() => folderInput.current?.click()}>
              Choose folder
            </Button>
          </div>
          <input ref={fileInput} type="file" multiple hidden accept="image/*,video/*" onChange={(e) => pick(e.target.files)} />
          <input
            ref={folderInput}
            type="file"
            hidden
            // @ts-expect-error non-standard but supported by all major browsers
            webkitdirectory=""
            onChange={(e) => pick(e.target.files)}
          />
        </div>
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. living room handheld" />
        </Field>
        {progress != null && <ProgressBar value={progress} />}
        <ErrorBanner error={error} />
        <p className="text-xs text-faint">Large videos upload slowly through the browser; if the files are already on the server machine, import by path instead.</p>
        <Button variant="primary" disabled={!files.length} loading={progress != null} onClick={submit}>
          Upload
        </Button>
      </div>
    </Card>
  );
}

function ImportCard({ onDone }: { onDone: () => void }) {
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [link, setLink] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Capture | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      setCreated(await api.importCapture({ path: path.trim(), name: name.trim() || undefined, link }));
      setPath("");
      setName("");
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Import from a path on the server">
      <div className="space-y-3 p-4">
        <Field label="Path" help="A video file, or a folder of photos (searched recursively).">
          <Input value={path} onChange={(e) => setPath(e.target.value)} placeholder="/home/you/scans/room1.mp4" className="font-mono" />
        </Field>
        <Field label="Name (optional)">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="defaults to the file or folder name" />
        </Field>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" checked={link} onChange={(e) => setLink(e.target.checked)} className="mt-0.5 accent-[var(--color-accent)]" />
          <span>
            Link instead of copying
            <span className="block text-xs text-faint">Saves disk space for big recordings; the original must stay where it is.</span>
          </span>
        </label>
        <ErrorBanner error={error} />
        {created && (
          <p className="text-sm text-ok">
            Imported “{created.name}”.{" "}
            <Link to={`/runs/new?capture=${created.id}`} className="underline">
              Start a run
            </Link>
          </p>
        )}
        <Button variant="primary" disabled={!path.trim()} loading={busy} onClick={submit}>
          Import
        </Button>
      </div>
    </Card>
  );
}
