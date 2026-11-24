import io
import json
import wave
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.main import create_app, segments


def test_segment_boundaries():
    text = "中文。English! More words. 中文？" * 70
    parts = list(segments(text))
    assert max(map(len, parts)) <= 300
    assert "".join("".join(parts).split()) == "".join(text.split())


def test_local_mock_stream_and_wav(tmp_path):
    headers = {"Authorization": "Bearer secret"}
    with TestClient(create_app(tmp_path, "secret", mock=True),
                    base_url="http://127.0.0.1:8123") as client:
        assert client.get("/api/v1/health").status_code == 401
        assert client.get("/api/v1/health", headers=headers).json()["mode"] == "mock"
        assert client.get("/api/v1/health", headers={**headers, "Origin": "https://example.com"}).status_code == 403
        task_id = uuid4()
        url = f"/api/v1/tts/stream/{task_id}"
        assert client.post(url, json={"text": " ", "model": "../../escape"}, headers=headers).status_code == 422
        response = client.post(url, json={"text": "Hello from Studio"}, headers=headers)
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[0]["rate"] == 24000
        assert events[-1]["result"]["mock"] is True
        assert client.get("/api/v1/history", headers=headers).json()[0]["id"] == str(task_id)
        wav = client.get(f"/api/v1/history/{task_id}/audio", headers=headers)
        with wave.open(io.BytesIO(wav.content)) as audio:
            assert audio.getnframes() == 19200
        merged = client.post("/api/v1/exports", headers=headers, json={
            "format": "wav", "clips": [{"id": str(task_id), "pause_ms": 250}, {"id": str(task_id)}],
        })
        with wave.open(io.BytesIO(merged.content)) as audio:
            assert audio.getnframes() == 44400
        assert list((tmp_path / "runtime").iterdir()) == []


def test_reference_and_voice_survive_restart(tmp_path):
    headers = {"Authorization": "Bearer secret"}
    with TestClient(create_app(tmp_path, "secret", mock=True), headers=headers,
                    base_url="http://127.0.0.1:8123") as client:
        invalid = client.post("/api/v1/references", files={"file": ("bad.wav", b"no audio")})
        assert invalid.status_code == 422
        content = io.BytesIO()
        with wave.open(content, "wb") as wav:
            wav.setparams((1, 2, 24000, 0, "NONE", ""))
            wav.writeframes(b"\x00\x00" * 2400)
        upload = client.post("/api/v1/references", files={"file": ("../../sample.wav", content.getvalue())})
        reference = upload.json()["id"]
        assert client.post("/api/v1/voices", json={"name": "Voice", "reference": reference}).status_code == 422
        voice = client.post("/api/v1/voices", json={"name": "Voice", "reference": reference, "xvec": True}).json()
        assert client.get(f"/api/v1/references/{reference}/audio").content == content.getvalue()
        package = client.get(f"/api/v1/voices/{voice['id']}/package").content
        imported = client.post("/api/v1/voices/import", files={"file": ("voice.json", package)}).json()
        assert imported["id"] != voice["id"]
        assert client.get(f"/api/v1/references/{imported['reference']}/audio").content == content.getvalue()
        assert client.delete(f"/api/v1/voices/{imported['id']}").status_code == 200
    with TestClient(create_app(tmp_path, "secret", mock=True), headers=headers,
                    base_url="http://127.0.0.1:8123") as client:
        assert client.get("/api/v1/voices").json() == [voice]
        assert client.delete("/api/v1/voices/" + voice["id"]).status_code == 200
        assert client.get("/api/v1/voices").json() == []


def test_cache_cleanup_preserves_other_files(tmp_path):
    cache = tmp_path / "cache"
    hub = cache / "huggingface"
    hub.mkdir(parents=True)
    (hub / "cache.bin").write_bytes(b"cache")
    keep = cache / "keep.txt"
    keep.write_text("keep")
    headers = {"Authorization": "Bearer secret"}
    with TestClient(create_app(tmp_path, "secret", cache=cache), headers=headers,
                    base_url="http://127.0.0.1:8123") as client:
        assert client.post("/api/v1/storage/cache/clear").json() == {"cleared": True}
        assert not hub.exists()
        assert keep.read_text() == "keep"


def test_dialogue_workspace_survives_restart(tmp_path):
    headers = {"Authorization": "Bearer secret"}
    saved = {"roles": [{"name": "Narrator", "voice": "Vivian"}],
             "rows": [{"id": 1, "text": "First line", "role": 0, "pause": 500, "result": None}],
             "custom": "0.6b-customvoice", "base": "0.6b-base",
             "quant": "Q8_0", "language": "English"}
    with TestClient(create_app(tmp_path, "secret"), headers=headers,
                    base_url="http://127.0.0.1:8123") as client:
        assert client.put("/api/v1/workspaces/dialogue", json=saved).status_code == 200
        assert client.put("/api/v1/settings", json={"theme": "dark", "locale": "en"}).status_code == 200
    with TestClient(create_app(tmp_path, "secret"), headers=headers,
                    base_url="http://127.0.0.1:8123") as client:
        assert client.get("/api/v1/workspaces/dialogue").json() == saved
        assert client.get("/api/v1/workspaces/batch").json() is None
        assert client.get("/api/v1/settings").json() == {"theme": "dark", "locale": "en"}
