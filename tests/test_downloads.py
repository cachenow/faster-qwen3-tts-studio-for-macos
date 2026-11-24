import asyncio
import hashlib
import time

import httpx
from fastapi.testclient import TestClient

from backend import downloads
from backend.catalog import filenames
from backend.main import create_app


def test_resume_and_verify(tmp_path, monkeypatch):
    name = "sample.gguf"
    data = b"GGUF test weight"
    (tmp_path / "sample.part").write_bytes(data[:4])
    monkeypatch.setitem(downloads.CATALOG["files"], name, {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    def endpoint(request):
        assert request.headers["range"] == "bytes=4-"
        return httpx.Response(206, headers={"Content-Range": f"bytes 4-{len(data)-1}/{len(data)}"}, content=data[4:])
    client = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))
    monkeypatch.setattr(downloads.httpx, "AsyncClient", lambda **kwargs: client)
    progress = []
    asyncio.run(downloads.download_weight(tmp_path, name, lambda *args: progress.append(args), "mirror"))
    assert (tmp_path / name).read_bytes() == data
    assert downloads.installed(tmp_path, name)
    assert [p[1] for p in progress] == [4, len(data)]


def test_download_control_and_storage(tmp_path, monkeypatch):
    model, quant = "0.6b-base", "Q8_0"
    name = filenames(model, quant)[0]
    async def slow(directory, file, progress, source):
        (directory / file).with_suffix(".part").write_bytes(b"GGUF")
        progress(file, 4, 10)
        await asyncio.sleep(60)
    monkeypatch.setattr("backend.main.download_weight", slow)
    with TestClient(create_app(tmp_path, "test"), base_url="http://127.0.0.1:1234",
                    headers={"Authorization":"Bearer test"}) as client:
        base = "/api/v1/models/download"
        def start():
            assert client.post(base, json={"model":model, "quant":quant}).status_code == 202
        def wait_for(state):
            for _ in range(100):
                job = client.get(base).json()
                if job["state"] == state:
                    return job
                time.sleep(.01)
            raise AssertionError(job)
        start()
        assert wait_for("downloading")["received"] == 4
        assert client.post("/api/v1/storage/clear", json=["models"]).status_code == 409
        assert client.post(base+"/pause").is_success
        wait_for("paused")
        partial = (tmp_path / "models" / name).with_suffix(".part")
        assert partial.exists()
        start()
        assert client.post(base+"/cancel").is_success
        wait_for("cancelled")
        assert not partial.exists()
        (tmp_path / "models" / "keep.gguf").write_bytes(b"keep")
        partial.write_bytes(b"test")
        assert client.get("/api/v1/storage").json()["partials"] == 4
        assert client.post("/api/v1/storage/clear", json=["partials"]).is_success
        assert not partial.exists()
        assert (tmp_path / "models" / "keep.gguf").read_bytes() == b"keep"
