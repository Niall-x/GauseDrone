"""API + runner tests with fake stages (no COLMAP/GPU needed): `pytest tests`."""
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.server import main, stages
from app.server.stages import Param, Stage


def fake_stages() -> list[Stage]:
    def stage(name, needs_input=False):
        return Stage(
            name=name,
            label=name.title(),
            module="tests.fake_stage",
            description="fake",
            outputs=[name],
            needs_input=needs_input,
            params=[
                Param("name", "Name", "choice", name, choices=[name]),
                Param("value", "Value", "int", 1, min=0, max=100),
                Param("sleep", "Sleep", "float", 0.0, min=0, max=60),
                Param("fail", "Fail", "int", 0, min=0, max=1),
            ],
        )

    return [stage("a", needs_input=True), stage("b"), stage("c")]


@pytest.fixture
def client(tmp_path, monkeypatch):
    original = list(stages.STAGES)
    stages.STAGES[:] = fake_stages()
    stages.STAGE_BY_NAME.clear()
    stages.STAGE_BY_NAME.update({s.name: s for s in stages.STAGES})
    monkeypatch.setattr(main, "DATA_DIR", tmp_path / "data")
    with TestClient(main.app) as c:
        yield c
    stages.STAGES[:] = original
    stages.STAGE_BY_NAME.clear()
    stages.STAGE_BY_NAME.update({s.name: s for s in original})


@pytest.fixture
def capture(client, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    for i in range(3):
        cv2.imwrite(str(photos / f"img{i}.jpg"), np.full((40, 60, 3), i * 60, np.uint8))
    r = client.post("/api/captures/import", json={"path": str(photos), "name": "test scene"})
    assert r.status_code == 200, r.text
    return r.json()


def wait(client, run_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish: {run}")


def test_capture_import(capture, client):
    assert capture["kind"] == "images"
    assert capture["num_images"] == 3
    assert capture["resolution"] == [60, 40]
    assert client.get(f"/api/captures/{capture['id']}/thumb").status_code == 200


def test_import_rejects_mixed_or_missing(client, tmp_path):
    assert client.post("/api/captures/import", json={"path": str(tmp_path / "nope")}).status_code == 400
    empty = tmp_path / "empty"
    empty.mkdir()
    assert client.post("/api/captures/import", json={"path": str(empty)}).status_code == 400


def test_run_completes(client, capture):
    run = client.post("/api/runs", json={"capture_id": capture["id"], "config": {"b": {"value": 7}}}).json()
    run = wait(client, run["id"])
    assert run["status"] == "done"
    a, b, c = run["stages"]
    assert all(s["status"] == "done" and s["progress"] == 1.0 for s in run["stages"])
    assert a["result"] == {"value": 1, "had_input": True}
    assert b["result"]["value"] == 7 and b["result"]["had_input"] is False
    assert run["env"]["torch"]  # tool versions recorded
    log = client.get(f"/api/runs/{run['id']}/log/b").text
    assert "some ordinary log output" in log and "@@progress" not in log
    assert client.get(f"/api/runs/{run['id']}/files/b/marker.txt").text == "value=7"


def test_invalid_config_rejected(client, capture):
    r = client.post("/api/runs", json={"capture_id": capture["id"], "config": {"b": {"value": 1000}}})
    assert r.status_code == 400
    r = client.post("/api/runs", json={"capture_id": capture["id"], "config": {"zzz": {}}})
    assert r.status_code == 400


def test_failure_then_resume(client, capture):
    run = client.post("/api/runs", json={"capture_id": capture["id"], "config": {"b": {"fail": 1}}}).json()
    run = wait(client, run["id"])
    assert run["status"] == "failed"
    assert [s["status"] for s in run["stages"]] == ["done", "failed", "pending"]
    assert "failed on purpose" in run["stages"][1]["error"]

    # fix the setting and re-run from the failed stage; stage a is kept
    a_finished = run["stages"][0]["finished"]
    r = client.post(f"/api/runs/{run['id']}/rerun", json={"from_stage": "b", "config": {"b": {"fail": 0}}})
    assert r.status_code == 200, r.text
    run = wait(client, run["id"])
    assert run["status"] == "done"
    assert run["stages"][0]["finished"] == a_finished


def test_rerun_cannot_change_earlier_stage(client, capture):
    run = wait(client, client.post("/api/runs", json={"capture_id": capture["id"]}).json()["id"])
    r = client.post(f"/api/runs/{run['id']}/rerun", json={"from_stage": "c", "config": {"a": {"value": 3}}})
    assert r.status_code == 400


def test_reuse_from_base_run(client, capture):
    base = wait(client, client.post("/api/runs", json={"capture_id": capture["id"]}).json()["id"])
    run = client.post(
        "/api/runs",
        json={"capture_id": capture["id"], "base_run_id": base["id"], "reuse_until": "b", "config": {"c": {"value": 9}}},
    ).json()
    run = wait(client, run["id"])
    assert run["status"] == "done"
    assert run["stages"][0]["reused_from"] == base["id"]
    assert run["stages"][1]["reused_from"] == base["id"]
    assert run["stages"][2]["reused_from"] is None and run["stages"][2]["result"]["value"] == 9
    assert client.get(f"/api/runs/{run['id']}/files/a/marker.txt").status_code == 200
    # base untouched
    assert client.get(f"/api/runs/{base['id']}/files/c/marker.txt").text == "value=1"


def test_cancel_running(client, capture):
    run = client.post("/api/runs", json={"capture_id": capture["id"], "config": {"a": {"sleep": 30}}}).json()
    for _ in range(100):
        if client.get(f"/api/runs/{run['id']}").json()["stages"][0]["status"] == "running":
            break
        time.sleep(0.05)
    assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 200
    run = wait(client, run["id"], timeout=15)
    assert run["status"] == "cancelled"
    assert run["stages"][0]["status"] == "cancelled"
    assert run["stages"][1]["status"] == "pending"


def test_delete_guards(client, capture):
    run = wait(client, client.post("/api/runs", json={"capture_id": capture["id"]}).json()["id"])
    assert client.delete(f"/api/captures/{capture['id']}").status_code == 409  # still used by a run
    assert client.delete(f"/api/runs/{run['id']}").status_code == 200
    assert client.delete(f"/api/captures/{capture['id']}").status_code == 200


def test_file_access_confined_to_run(client, capture):
    run = wait(client, client.post("/api/runs", json={"capture_id": capture["id"]}).json()["id"])
    assert client.get(f"/api/runs/{run['id']}/files/../../captures/{capture['id']}/capture.json").status_code == 404
    assert client.get(f"/api/runs/{run['id']}/files/%2e%2e/%2e%2e/captures/{capture['id']}/capture.json").status_code == 404


def test_upload_capture(client):
    ok, jpg = cv2.imencode(".jpg", np.full((30, 50, 3), 128, np.uint8))
    files = [("files", (f"frame{i}.jpg", jpg.tobytes(), "image/jpeg")) for i in range(2)]
    r = client.post("/api/captures/upload", data={"name": "uploaded"}, files=files)
    assert r.status_code == 200, r.text
    cap = r.json()
    assert cap["kind"] == "images" and cap["num_images"] == 2 and cap["origin"] == "upload"

    bad = client.post("/api/captures/upload", data={"name": "junk"}, files=[("files", ("notes.txt", b"hi", "text/plain"))])
    assert bad.status_code == 400
    assert len(client.get("/api/captures").json()) == 1  # the rejected upload left nothing behind


def test_shutdown_interrupts_and_restart_recovers(client, capture):
    first = client.post("/api/runs", json={"capture_id": capture["id"], "config": {"a": {"sleep": 30}}}).json()
    second = client.post("/api/runs", json={"capture_id": capture["id"]}).json()
    for _ in range(100):
        if client.get(f"/api/runs/{first['id']}").json()["stages"][0]["status"] == "running":
            break
        time.sleep(0.05)
    t0 = time.time()
    client.__exit__(None, None, None)  # server shutdown: must stop the stage, not wait 30 s
    assert time.time() - t0 < 10

    with TestClient(main.app) as c2:  # restart on the same data dir
        r1 = c2.get(f"/api/runs/{first['id']}").json()
        assert r1["status"] == "failed" and "interrupted" in r1["stages"][0]["error"]
        assert r1["stages"][0]["pid"] is None
        assert wait(c2, second["id"])["status"] == "done"  # the queued run survived the restart
        assert c2.post(f"/api/runs/{first['id']}/resume").status_code == 200
        c2.post("/api/runs/{}/cancel".format(first["id"]))  # (stage a sleeps 30 s; no need to wait)


def test_upload_keeps_duplicate_names(client):
    ok, jpg = cv2.imencode(".jpg", np.full((30, 50, 3), 128, np.uint8))
    files = [("files", (name, jpg.tobytes(), "image/jpeg")) for name in ("DCIM/100/IMG_0001.jpg", "DCIM/101/IMG_0001.jpg")]
    cap = client.post("/api/captures/upload", data={"name": "dup"}, files=files).json()
    assert cap["num_images"] == 2 and sorted(cap["files"]) == ["IMG_0001.jpg", "IMG_0001_2.jpg"]


def test_stage_killed_externally_is_interrupted(client, capture):
    import os
    import signal

    run = client.post("/api/runs", json={"capture_id": capture["id"], "config": {"a": {"sleep": 30}}}).json()
    for _ in range(100):
        pid = client.get(f"/api/runs/{run['id']}").json()["stages"][0]["pid"]
        if pid:
            break
        time.sleep(0.05)
    os.killpg(pid, signal.SIGTERM)  # as `systemctl stop` would, before the server notices
    run = wait(client, run["id"])
    assert run["status"] == "failed"
    assert "interrupted" in run["stages"][0]["error"]
