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
                Param("garbage", "Garbage", "int", 0, min=0, max=1),
                Param("unreliable", "Unreliable", "int", 0, min=0, max=1),
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
    monkeypatch.setattr(main, "IMPORT_ROOTS", [tmp_path.resolve()])
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


def test_import_confined_to_roots(client, tmp_path, monkeypatch):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    cv2.imwrite(str(outside / "a.jpg"), np.zeros((8, 8, 3), np.uint8))
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(main, "IMPORT_ROOTS", [allowed.resolve()])
    assert client.post("/api/captures/import", json={"path": str(outside)}).status_code == 403
    (allowed / "sneaky").symlink_to(outside)  # a symlink inside the root must not reach outside it
    assert client.post("/api/captures/import", json={"path": str(allowed / "sneaky")}).status_code == 403
    hidden = allowed / ".secret"
    hidden.mkdir()
    cv2.imwrite(str(hidden / "a.jpg"), np.zeros((8, 8, 3), np.uint8))
    assert client.post("/api/captures/import", json={"path": str(hidden)}).status_code == 403
    assert client.get("/api/captures").json() == []


def test_import_validates_before_copying(client, tmp_path):
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    (mixed / "a.mp4").write_bytes(b"x")
    (mixed / "b.mp4").write_bytes(b"x")
    r = client.post("/api/captures/import", json={"path": str(mixed)})
    assert r.status_code == 400 and "2 videos" in r.text
    assert not any((tmp_path / "data" / "captures").iterdir())  # nothing was copied


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


def jpeg(value=128) -> bytes:
    return cv2.imencode(".jpg", np.full((30, 50, 3), value, np.uint8))[1].tobytes()


def upload(client, name, files: dict[str, bytes], chunk=1000):
    up = client.post("/api/uploads", json={"name": name, "files": [{"source": s, "size": len(b)} for s, b in files.items()]})
    assert up.status_code == 200, up.text
    up = up.json()
    for i, data in enumerate(files.values()):
        for off in range(0, len(data), chunk):
            r = client.put(f"/api/uploads/{up['id']}/files/{i}?offset={off}", content=data[off : off + chunk])
            assert r.status_code == 200, r.text
    return up


def test_upload_capture(client):
    up = upload(client, "uploaded", {"frame0.jpg": jpeg(), "frame1.jpg": jpeg(90)})
    r = client.post(f"/api/uploads/{up['id']}/finish")
    assert r.status_code == 200, r.text
    cap = r.json()
    assert cap["kind"] == "images" and cap["num_images"] == 2 and cap["origin"] == "upload"
    assert client.get("/api/uploads").json() == []  # finished uploads are cleaned up

    # a set of files that can't be a capture is refused before any bytes are sent
    bad = client.post("/api/uploads", json={"name": "junk", "files": [{"source": "notes.txt", "size": 2}]})
    assert bad.status_code == 400
    bad = client.post("/api/uploads", json={"name": "junk", "files": [{"source": "../../x.jpg", "size": 2}, {"source": "..", "size": 2}]})
    assert bad.status_code == 400
    assert len(client.get("/api/captures").json()) == 1 and client.get("/api/uploads").json() == []


def test_upload_resumes(client):
    data = jpeg() * 5
    up = client.post("/api/uploads", json={"name": "big", "files": [{"source": "DCIM/big.jpg", "size": len(data)}]}).json()
    put = lambda off, chunk: client.put(f"/api/uploads/{up['id']}/files/0?offset={off}", content=chunk)  # noqa: E731
    assert put(0, data[:1000]).status_code == 200
    assert client.post(f"/api/uploads/{up['id']}/finish").status_code == 400  # not complete yet
    # the connection dropped after the server got the chunk; the client retries it
    r = put(0, data[:1000])
    assert r.status_code == 409 and r.json()["detail"]["received"] == 1000
    assert put(5000, data[5000:]).status_code == 409  # can't skip ahead either
    # the state survives a server restart: continue from where the server says
    client.__exit__(None, None, None)
    with TestClient(main.app) as c2:
        (state,) = c2.get("/api/uploads").json()
        assert state["id"] == up["id"] and state["files"][0]["received"] == 1000 and state["files"][0]["source"] == "DCIM/big.jpg"
        assert c2.put(f"/api/uploads/{up['id']}/files/0?offset=1000", content=data[1000:]).status_code == 200
        assert c2.put(f"/api/uploads/{up['id']}/files/0?offset={len(data)}", content=b"x").status_code == 400  # past the end
        cap = c2.post(f"/api/uploads/{up['id']}/finish").json()
        assert cap["files"] == ["big.jpg"] and cap["size_bytes"] == len(data)


def test_upload_discard(client):
    up = client.post("/api/uploads", json={"name": "x", "files": [{"source": "a.mp4", "size": 10}]}).json()
    assert client.delete(f"/api/uploads/{up['id']}").status_code == 200
    assert client.get("/api/uploads").json() == []
    assert client.put(f"/api/uploads/{up['id']}/files/0?offset=0", content=b"x").status_code == 404


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
    up = upload(client, "dup", {"DCIM/100/IMG_0001.jpg": jpeg(), "DCIM/101/IMG_0001.jpg": jpeg(60)})
    cap = client.post(f"/api/uploads/{up['id']}/finish").json()
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


def test_malformed_protocol_lines_are_logged_not_fatal(client, capture):
    run = wait(client, client.post("/api/runs", json={"capture_id": capture["id"], "config": {"a": {"garbage": 1}}}).json()["id"])
    assert run["status"] == "done", run
    assert run["stages"][0]["result"]["value"] == 1
    log = client.get(f"/api/runs/{run['id']}/log/a").text
    assert "@@progress not-a-number" in log and "@@result {truncated" in log


def test_failed_finish_keeps_the_uploaded_bytes(client, monkeypatch):
    up = upload(client, "keep", {"a.jpg": jpeg(), "b.jpg": jpeg(90)})

    def boom(*args, **kwargs):
        raise RuntimeError("disk hiccup")
    monkeypatch.setattr(main.store, "finalize_capture", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/uploads/{up['id']}/finish")
    (state,) = client.get("/api/uploads").json()
    assert [f["received"] for f in state["files"]] == [f["size"] for f in state["files"]]  # nothing lost
    assert client.get("/api/captures").json() == []
    monkeypatch.undo()
    assert client.post(f"/api/uploads/{up['id']}/finish").status_code == 200


def test_upload_rejects_unusable_names(client):
    for bad in ("x" * 250 + ".jpg", "a\0b.jpg", ".hidden.jpg"):
        r = client.post("/api/uploads", json={"name": "n", "files": [{"source": bad, "size": 1}]})
        assert r.status_code == 400, bad
    assert client.get("/api/uploads").json() == []
    assert not any((main.DATA_DIR / "uploads").iterdir())  # no half-created upload folders


def test_run_files_revalidate(client, capture):
    run = wait(client, client.post("/api/runs", json={"capture_id": capture["id"]}).json()["id"])
    url = f"/api/runs/{run['id']}/files/a/marker.txt"
    r = client.get(url)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache" and r.headers.get("etag")
    same = client.get(url, headers={"If-None-Match": r.headers["etag"]})
    assert same.status_code == 304 and same.content == b""  # unchanged: the browser keeps its copy
    time.sleep(0.01)
    (main.store.run_dir(run["id"]) / "a" / "marker.txt").write_text("value=2")  # e.g. a re-run rewrote it
    changed = client.get(url, headers={"If-None-Match": r.headers["etag"]})
    assert changed.status_code == 200 and changed.text == "value=2"


def test_unreliable_result_pauses_before_next_stage(client, capture):
    run = client.post("/api/runs", json={"capture_id": capture["id"], "config": {"b": {"unreliable": 1}}}).json()
    run = wait(client, run["id"])
    assert run["status"] == "paused"
    assert [s["status"] for s in run["stages"]] == ["done", "done", "pending"]
    # "train anyway": resuming carries on without re-checking the paused stage
    assert client.post(f"/api/runs/{run['id']}/resume").status_code == 200
    run = wait(client, run["id"])
    assert run["status"] == "done"


def test_paused_run_can_be_cancelled(client, capture):
    run = client.post("/api/runs", json={"capture_id": capture["id"], "config": {"b": {"unreliable": 1}}}).json()
    assert wait(client, run["id"])["status"] == "paused"
    r = client.post(f"/api/runs/{run['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
