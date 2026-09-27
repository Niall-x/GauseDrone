"""Background job runner: one worker thread, one run at a time (the GPU is the
bottleneck), each stage a subprocess whose stdout goes to logs/<stage>.log.

Stage CLIs report progress with `@@progress` / `@@result` lines (see
pipeline/common.py). Cancelling kills the stage's whole process group.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from app.server.models import Run, now
from app.server.stages import STAGE_BY_NAME
from app.server.store import Store

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PERSIST_EVERY_SEC = 2.0


class Runner:
    def __init__(self, store: Store):
        self.store = store
        self.queue: deque[str] = deque()
        self.cond = threading.Condition()
        self.current: str | None = None
        self.proc: subprocess.Popen | None = None
        self.cancel_requested = False
        self._recover()
        self.thread = threading.Thread(target=self._loop, name="runner", daemon=True)
        self.thread.start()

    # --- public API ---

    def enqueue(self, run_id: str) -> None:
        with self.cond:
            if run_id != self.current and run_id not in self.queue:
                self.queue.append(run_id)
            self.cond.notify()

    def is_active(self, run_id: str) -> bool:
        with self.cond:
            return run_id == self.current or run_id in self.queue

    def queue_position(self, run_id: str) -> int | None:
        with self.cond:
            return list(self.queue).index(run_id) + 1 if run_id in self.queue else None

    def cancel(self, run_id: str) -> bool:
        with self.cond:
            if run_id in self.queue:
                self.queue.remove(run_id)
                self.store.update_run(run_id, lambda r: setattr(r, "status", "cancelled"))
                return True
            if run_id != self.current:
                return False
            self.cancel_requested = True
            proc = self.proc
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return True

    # --- internals ---

    def _recover(self) -> None:
        """After a restart: re-queue queued runs, mark interrupted ones failed (resumable)."""
        for run in sorted(self.store.list_runs(), key=lambda r: r.created):
            if run.status == "queued":
                self.queue.append(run.id)
            elif run.status == "running":
                def interrupted(r: Run):
                    r.status = "failed"
                    for s in r.stages:
                        if s.status == "running":
                            s.status, s.error, s.finished = "failed", "interrupted: the server stopped mid-stage", now()
                self.store.update_run(run.id, interrupted)

    def _loop(self) -> None:
        while True:
            with self.cond:
                while not self.queue:
                    self.cond.wait()
                self.current = self.queue.popleft()
                self.cancel_requested = False
            try:
                self._execute(self.current)
            except Exception as e:  # never let one bad run kill the worker
                run_id = self.current
                self.store.update_run(run_id, lambda r: setattr(r, "status", "failed"))
                print(f"runner: run {run_id} crashed: {e!r}", file=sys.stderr)
            finally:
                with self.cond:
                    self.current, self.proc = None, None

    def _execute(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if run is None:
            return
        self.store.update_run(run_id, lambda r: setattr(r, "status", "running"))
        for stage_state in run.stages:
            if stage_state.status == "done":
                continue
            ok = not self.cancel_requested and self._run_stage(run, stage_state.name)
            if not ok:
                status = "cancelled" if self.cancel_requested else "failed"
                self.store.update_run(run_id, lambda r: setattr(r, "status", status))
                return
        self.store.update_run(run_id, lambda r: setattr(r, "status", "done"))

    def _command(self, run: Run, stage_name: str) -> list[str]:
        stage = STAGE_BY_NAME[stage_name]
        cmd = [sys.executable, "-u", "-m", stage.module, "--run-dir", str(self.store.run_dir(run.id))]
        if stage.needs_input:
            cmd += ["--input", str(self.store.capture_dir(run.capture_id) / "source")]
        for key, value in run.config.get(stage_name, {}).items():
            cmd += [f"--{key}", str(value)]
        return cmd

    def _run_stage(self, run: Run, stage_name: str) -> bool:
        run_dir = self.store.run_dir(run.id)
        log_path = run_dir / "logs" / f"{stage_name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = self._command(run, stage_name)

        def start(r: Run):
            s = r.stage(stage_name)
            s.status, s.progress, s.message, s.error = "running", 0.0, "starting", None
            s.started, s.finished, s.result = now(), None, {}
        self.store.update_run(run.id, start)

        env = dict(os.environ)
        env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        tail: deque[str] = deque(maxlen=25)
        with open(log_path, "w") as log:
            log.write(f"$ {' '.join(cmd)}\n")
            log.flush()
            proc = subprocess.Popen(
                cmd, cwd=PROJECT_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, start_new_session=True,
            )
            with self.cond:
                self.proc = proc
            last_persist = 0.0
            for line in proc.stdout:
                if line.startswith("@@progress "):
                    _, frac, *msg = line.rstrip("\n").split(" ", 2)
                    def tick(r: Run, frac=float(frac), msg=msg[0] if msg else ""):
                        s = r.stage(stage_name)
                        s.progress, s.message = frac, msg
                    persist = time.monotonic() - last_persist > PERSIST_EVERY_SEC
                    self.store.update_run(run.id, tick, persist=persist)
                    if persist:
                        last_persist = time.monotonic()
                    continue
                if line.startswith("@@result "):
                    values = json.loads(line[len("@@result "):])
                    self.store.update_run(run.id, lambda r: r.stage(stage_name).result.update(values))
                    continue
                log.write(line)
                log.flush()
                tail.append(line.rstrip())
            code = proc.wait()

        cancelled = self.cancel_requested

        def finish(r: Run):
            s = r.stage(stage_name)
            s.finished = now()
            if code == 0:
                s.status, s.progress = "done", 1.0
            elif cancelled:
                s.status, s.error = "cancelled", "cancelled by user"
            else:
                s.status = "failed"
                s.error = "\n".join(list(tail)[-12:]) or f"exited with code {code}"
        self.store.update_run(run.id, finish)
        return code == 0
