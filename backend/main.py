import asyncio
import base64
import hmac
import hashlib
import json
import multiprocessing
import os
import platform
import re
import secrets
import shutil
import socket
import sqlite3
import threading
import time
import wave
from contextlib import closing
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field, model_validator

from .catalog import VARIANTS, QUANTS, filenames, model_id
from .downloads import CATALOG, download_weight, installed
from .engine import MetalEngine, MockEngine


class WeightSelection(BaseModel):
    source: Literal["official", "mirror"] = "official"
    model: Literal["0.6b-base", "1.7b-base", "0.6b-customvoice", "1.7b-customvoice", "1.7b-voicedesign"]
    quant: Literal["BF16", "Q8_0", "Q4_K_M"]


class VoiceMetadata(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    transcript: str = Field(default="", max_length=5000)
    notes: str = Field(default="", max_length=2000)
    xvec: bool = False
    tags: list[str] = Field(default_factory=list, max_length=12)
    favorite: bool = False


class Voice(VoiceMetadata):
    reference: UUID


class VoicePackage(BaseModel):
    format: Literal["fqt-studio-voice-v1"]
    audio: str = Field(max_length=45_000_000)
    voice: VoiceMetadata


class ExportClip(BaseModel):
    id: UUID
    pause_ms: int = Field(default=0, ge=0, le=10000)


class ExportRequest(BaseModel):
    format: Literal["wav", "zip"]
    clips: list[ExportClip] = Field(min_length=1, max_length=50)


class WorkspaceRole(BaseModel):
    name: str = Field(max_length=80)
    voice: str = Field(min_length=1, max_length=80)


class WorkspaceClip(BaseModel):
    id: int = Field(ge=1)
    text: str = Field(max_length=12000)
    role: int = Field(ge=0, lt=12)
    pause: int = Field(ge=0, le=10000)
    result: UUID | None = None


class Workspace(BaseModel):
    roles: list[WorkspaceRole] = Field(min_length=1, max_length=12)
    rows: list[WorkspaceClip] = Field(max_length=50)
    custom: Literal["0.6b-customvoice", "1.7b-customvoice"]
    base: Literal["0.6b-base", "1.7b-base"]
    quant: Literal["BF16", "Q8_0", "Q4_K_M"]
    language: str = Field(min_length=1, max_length=30)


class Preferences(BaseModel):
    locale: Literal["zh", "en"]
    theme: Literal["system", "light", "dark"]


class Generation(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    model: str = "0.6b-customvoice"
    quant: Literal["BF16", "Q8_0", "Q4_K_M"] = "Q8_0"
    language: str = Field(default="Auto", max_length=30)
    speaker: str = Field(default="Vivian", max_length=60)
    instruct: str = Field(default="", max_length=2000)
    reference: UUID | None = None
    transcript: str = Field(default="", max_length=5000)
    xvec: bool = False
    temperature: float = Field(default=0.9, gt=0, le=2)
    top_k: int = Field(default=50, ge=1, le=1000)
    top_p: float = Field(default=1, gt=0, le=1)
    max_new_tokens: int = Field(default=2048, ge=16, le=2048)

    @model_validator(mode="after")
    def validate_mode(self):
        if self.model not in VARIANTS or not self.text.strip():
            raise ValueError("Select a supported model and enter text")
        mode = VARIANTS[self.model]
        if mode == "clone" and (not self.reference or not (self.xvec or self.transcript.strip())):
            raise ValueError("Clone requires reference audio and ICL requires its transcript")
        if mode == "design" and not self.instruct.strip():
            raise ValueError("Voice design requires a description")
        return self


def segments(text, limit=300):
    pending = ""
    for part in re.split(r"(?<=[。！？!?；;\n])|(?<=\.)\s+", text):
        if pending.strip() and len(pending.strip()) + 1 + len(part) > limit:
            yield pending.strip()
            pending = ""
        while len(part) > limit:
            boundary = max(part.rfind(" ", 0, limit), part.rfind("，", 0, limit)) + 1
            boundary = boundary if boundary > limit // 2 else limit
            yield part[:boundary].strip()
            part = part[boundary:]
        pending += part + " "
    if pending.strip():
        yield pending.strip()


def infer(pipe, root, cache, data, mock):
    try:
        request = Generation.model_validate(data)
        mode = VARIANTS[request.model]
        talker, codec = (root / "models" / name for name in filenames(request.model, request.quant))
        options = {}
        if mode == "clone":
            options = dict(ref_audio=str(root / "voices" / f"{request.reference}.wav"),
                           ref_text=request.transcript, xvec_only=request.xvec)
        elif mode == "custom":
            options = dict(speaker=request.speaker, instruct=request.instruct or None)
        else:
            options = dict(instruct=request.instruct)
        options.update(temperature=request.temperature, top_k=request.top_k,
                       top_p=request.top_p, max_new_tokens=request.max_new_tokens)
        transcript_key = hashlib.sha256(request.transcript.encode("utf-8")).hexdigest()
        cache = cache / "qwentts-0.5.4-0.5.0" / request.model / request.quant / transcript_key
        engine = MockEngine() if mock else MetalEngine(cache)
        for text in segments(request.text):
            for rate, pcm in engine.stream(
                model_id(request.model), talker, codec, text, request.language, mode, **options
            ):
                pipe.send((rate, pcm))
        pipe.send((0, b""))
    except Exception as error:
        import logging

        logging.getLogger("uvicorn.error").error("Inference worker failed: %s", type(error).__name__)
        pipe.send(("inference_failed", None))
    finally:
        pipe.close()


class StorageAccess:
    """Keep destructive cleanup exclusive until concurrent responses finish using files."""
    def __init__(self, app):
        self.app = app
        self.in_use = 0
        self.cleaning = False

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/v1/") or path == "/api/v1/health":
            return await self.app(scope, receive, send)
        clean = scope["method"] == "POST" and path in ("/api/v1/storage/clear", "/api/v1/storage/cache/clear")
        if self.cleaning or (clean and self.in_use):
            return await JSONResponse({"detail": "Files are in use. Retry after the current operation."}, 409)(scope, receive, send)
        self.in_use += 1
        if clean:
            self.cleaning = True
        try:
            await self.app(scope, receive, send)
        finally:
            self.in_use -= 1
            if clean:
                self.cleaning = False


def create_app(root: Path, token: str, mock=False, cache: Path | None = None, logs: Path | None = None):
    root = root.resolve()
    cache = (cache or root / "cache").resolve()
    for folder in ("outputs", "voices", "database", "models", "config", "runtime"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    database = root / "database" / "studio.sqlite"
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS history (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        if db.execute("PRAGMA user_version").fetchone()[0] < 2:
            db.execute("CREATE TABLE IF NOT EXISTS voices (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("PRAGMA user_version = 2")
        if db.execute("PRAGMA user_version").fetchone()[0] < 3:
            db.execute("CREATE TABLE IF NOT EXISTS workspaces (kind TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("PRAGMA user_version = 3")
        if db.execute("PRAGMA user_version").fetchone()[0] < 4:
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("PRAGMA user_version = 4")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(StorageAccess)
    active = {}
    download_task = None
    download_status = {}
    confirmed_metal = False
    api = "/api/v1"

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        host = request.headers.get("host", "")
        if not re.fullmatch(r"127\.0\.0\.1(?::\d+)?", host):
            return JSONResponse({"error": "invalid_host"}, 403)
        origin = request.headers.get("origin")
        if origin not in (None, f"http://{host}"):
            return JSONResponse({"error": "invalid_origin"}, 403)
        if request.url.path.startswith(api):
            bearer = request.headers.get("authorization", "").encode()
            if not hmac.compare_digest(bearer, f"Bearer {token}".encode()):
                return JSONResponse({"error": "unauthorized"}, 401)
        return await call_next(request)

    @app.get(api + "/health")
    def health():
        return {"version": "0.1.0", "mode": "mock" if mock else "metal",
                "metalVerified": confirmed_metal, "platform": platform.platform(), "arch": platform.machine()}

    @app.get(api + "/system/diagnostics")
    def diagnostics():
        import importlib.metadata
        import sys

        versions = {"faster-qwen3-tts": "0.5.4 (GGML adapter)"}
        for package in ("qwentts-cpp-python",):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = None
        return {**health(), "python": platform.python_version(), "executable": sys.executable,
                "dataDirectory": str(root), "cacheDirectory": str(cache),
                "freeDiskBytes": shutil.disk_usage(root).free, "packages": versions}

    @app.get(api + "/settings")
    def settings():
        with closing(sqlite3.connect(database)) as db:
            row = db.execute("SELECT data FROM settings WHERE key = 'preferences'").fetchone()
        return json.loads(row[0]) if row else None

    @app.put(api + "/settings")
    def update_settings(preferences: Preferences):
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('preferences', ?)",
                       (preferences.model_dump_json(),))
        return preferences

    def data_files(group):
        locations = {"models": root / "models", "partials": root / "models", "voices": root / "voices",
                     "outputs": root / "outputs", "unused": root / "voices", "cache": cache, "logs": logs}
        directory = locations[group]
        if not directory or not directory.exists():
            return []
        if directory.is_symlink():
            raise HTTPException(409, "Data directory is a symbolic link")
        paths = list(directory.iterdir())
        if group == "unused":
            with closing(sqlite3.connect(database)) as db:
                saved = {json.loads(raw)["reference"] for raw, in db.execute("SELECT data FROM voices")}
            return [p for p in paths if p.suffix == ".wav" and p.stem not in saved]
        if group == "partials":
            return [p for p in paths if p.suffix == ".part"]
        if group == "models":
            return [p for p in paths if p.suffix in (".gguf", ".verified")]
        if group == "logs":
            return [p for p in paths if p.name in ("backend.log", "backend.previous.log")]
        return paths

    @app.get(api + "/storage")
    def storage():
        def size(path):
            try:
                if path.is_symlink():
                    return 0
                if path.is_dir():
                    return sum(size(child) for child in path.iterdir())
                return path.stat().st_size
            except FileNotFoundError:
                return 0

        return {**{key: sum(size(p) for p in data_files(key))
                   for key in ("models", "partials", "voices", "unused", "outputs", "cache", "logs")},
                "database": size(database)}

    @app.post(api + "/storage/clear")
    def clear_selected(groups: list[Literal["models","partials","voices","unused","outputs","cache","logs","workspaces","settings"]]):
        if active or download_status.get("active"):
            raise HTTPException(409, "Stop generation and pause downloads before cleaning data")
        with closing(sqlite3.connect(database)) as db, db:
            for group in set(groups):
                if group not in ("settings", "workspaces"):
                    for path in data_files(group):
                        if path.is_symlink():
                            path.unlink()
                        elif group == "logs" and path.name == "backend.log":
                            with path.open("wb"):
                                pass
                        elif path.is_dir():
                            shutil.rmtree(path)
                        else:
                            path.unlink(missing_ok=True)
                table = {"voices":"voices", "outputs":"history", "settings":"settings", "workspaces":"workspaces"}.get(group)
                if table:
                    db.execute(f"DELETE FROM {table}")
            if "workspaces" not in groups and ("voices" in groups or "outputs" in groups):
                for kind, raw in db.execute("SELECT kind,data FROM workspaces").fetchall():
                    workspace = json.loads(raw)
                    if "outputs" in groups:
                        for row in workspace["rows"]:
                            row["result"] = None
                    if "voices" in groups:
                        for role in workspace["roles"]:
                            try:
                                UUID(role["voice"])
                            except ValueError:
                                continue
                            role["voice"] = "Vivian"
                    db.execute("UPDATE workspaces SET data=? WHERE kind=?", (json.dumps(workspace),kind))
            db.commit()
            if any(key in groups for key in ("voices","outputs","settings","workspaces")):
                db.execute("VACUUM")
        if "models" in groups or "partials" in groups:
            download_status.clear()
        return {"cleared": groups}

    @app.post(api + "/storage/cache/clear")
    async def clear_cache():
        if active:
            raise HTTPException(409, "Stop generation before clearing the cache")
        for name in ("qwentts-0.5.4-0.5.0", "huggingface", "torch", "uv", "pycache"):
            directory = cache / name
            if directory.is_symlink():
                directory.unlink()
            elif directory.is_dir():
                shutil.rmtree(directory)
        return {"cleared": True}

    @app.get(api + "/models")
    def models():
        return [{"id": variant, "name": model_id(variant), "mode": mode,
                 "quantizations": [{"id": q, "downloadBytes": sum(CATALOG["files"][n]["bytes"] for n in filenames(variant, q) if not installed(root / "models", n)), "installed": all(
                     installed(root / "models", n) for n in filenames(variant, q)
                 )} for q in QUANTS]} for variant, mode in VARIANTS.items()]

    async def transfer(selection):
        def progress(name, offset, total):
            now = time.monotonic()
            if download_status["total"] == 0 or offset < download_status["received"]:
                download_status.update(started=now, initial=offset)
            speed = (offset - download_status["initial"]) / max(now - download_status["started"], 0.1)
            download_status.update(received=offset, total=total, bytesPerSecond=speed)

        try:
            for index, name in enumerate(filenames(selection.model, selection.quant), 1):
                download_status.update(file=name, part=index, received=0, total=0, bytesPerSecond=0)
                await download_weight(root / "models", name, progress, selection.source)
            download_status["state"] = "complete"
        except asyncio.CancelledError:
            if download_status["state"] == "cancelling":
                for name in filenames(selection.model, selection.quant):
                    (root / "models" / name).with_suffix(".part").unlink(missing_ok=True)
                download_status.update(state="cancelled", received=0, total=0)
            else:
                download_status["state"] = "paused"
        except Exception as exc:
            download_status.update(state="failed", error=str(exc) or type(exc).__name__)
        finally:
            download_status["active"] = False

    @app.post(api + "/models/download", status_code=202)
    async def download(selection: WeightSelection):
        nonlocal download_task
        if download_status.get("active"):
            raise HTTPException(409, "Another model download is active")
        download_status.clear()
        download_status.update(active=True, state="downloading", source=selection.source, model=selection.model, quant=selection.quant,
                               received=0, total=0, part=1, bytesPerSecond=0)
        download_task = asyncio.create_task(transfer(selection))
        return dict(download_status)

    @app.get(api + "/models/download")
    async def download_progress():
        return {"active": False, **download_status}

    @app.post(api + "/models/download/pause")
    async def pause_download():
        if download_status.get("active") and download_task and download_status["state"] == "downloading":
            download_task.cancel()
            download_status["state"] = "pausing"
        return dict(download_status)

    @app.post(api + "/models/download/cancel")
    async def cancel_download():
        if download_status.get("active") and download_task and download_status["state"] == "downloading":
            download_status["state"] = "cancelling"
            download_task.cancel()
        return dict(download_status)

    @app.delete(api + "/models/{variant}/{quant}")
    async def delete_weights(variant: str, quant: str):
        selection = WeightSelection.model_validate({"model": variant, "quant": quant})
        if active or download_status.get("active"):
            raise HTTPException(409, "Stop generation or download before removing a model")
        talker, codec = filenames(selection.model, selection.quant)
        shared = any(other != variant and installed(root / "models", filenames(other, quant)[0])
                     for other in VARIANTS)
        for name in (talker,) if shared else (talker, codec):
            path = root / "models" / name
            for target in (path, path.with_suffix(".verified"), path.with_suffix(".part")):
                target.unlink(missing_ok=True)
        if download_status.get("model") == variant and download_status.get("quant") == quant:
            download_status.clear()
        return {"model": variant, "quant": quant}

    def write_reference(content: bytes):
        if len(content) > 32 * 1024 * 1024:
            raise HTTPException(413, "Reference exceeds 32 MiB")
        from io import BytesIO
        try:
            with wave.open(BytesIO(content), "rb") as audio:
                if not audio.getnframes():
                    raise ValueError("Empty audio")
        except (wave.Error, EOFError, ValueError):
            raise HTTPException(422, "Upload a PCM WAV file") from None
        reference_id = uuid4()
        (root / "voices" / f"{reference_id}.wav").write_bytes(content)
        return reference_id

    @app.post(api + "/references")
    async def reference(file: UploadFile = File(...)):
        return {"id": write_reference(await file.read(32 * 1024 * 1024 + 1))}

    @app.get(api + "/voices")
    def voices():
        with closing(sqlite3.connect(database)) as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM voices ORDER BY rowid DESC")]

    def validate_voice(voice: VoiceMetadata):
        if not voice.name.strip() or not (voice.xvec or voice.transcript.strip()):
            raise HTTPException(422, "Enter a voice name and an ICL transcript")

    @app.post(api + "/voices")
    def save_voice(voice: Voice):
        validate_voice(voice)
        if not (root / "voices" / f"{voice.reference}.wav").is_file():
            raise HTTPException(404, "Reference audio missing")
        voice_id = str(uuid4())
        record = {"id": voice_id, **voice.model_dump(mode="json")}
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("INSERT INTO voices VALUES (?, ?)", (voice_id, json.dumps(record)))
        return record

    @app.put(api + "/voices/{voice_id}")
    def edit_voice(voice_id: UUID, voice: VoiceMetadata):
        validate_voice(voice)
        with closing(sqlite3.connect(database)) as db, db:
            row = db.execute("SELECT data FROM voices WHERE id = ?", (str(voice_id),)).fetchone()
            if row is None:
                raise HTTPException(404, "Voice missing")
            record = {**json.loads(row[0]), **voice.model_dump(mode="json")}
            db.execute("UPDATE voices SET data = ? WHERE id = ?", (json.dumps(record), str(voice_id)))
        return record

    @app.get(api + "/voices/{voice_id}/package")
    def voice_package(voice_id: UUID):
        with closing(sqlite3.connect(database)) as db:
            row = db.execute("SELECT data FROM voices WHERE id = ?", (str(voice_id),)).fetchone()
        if row is None:
            raise HTTPException(404, "Voice missing")
        voice = Voice.model_validate_json(row[0])
        path = root / "voices" / f"{voice.reference}.wav"
        if not path.is_file():
            raise HTTPException(404, "Reference audio missing")
        return {"format": "fqt-studio-voice-v1", "voice": voice.model_dump(exclude={"reference"}),
                "audio": base64.b64encode(path.read_bytes()).decode("ascii")}

    @app.post(api + "/voices/import")
    async def import_voice(file: UploadFile = File(...)):
        from binascii import Error
        from pydantic import ValidationError

        contents = await file.read(46_000_001)
        if len(contents) > 46_000_000:
            raise HTTPException(413, "Voice package too large")
        try:
            package = VoicePackage.model_validate_json(contents)
            audio = base64.b64decode(package.audio, validate=True)
        except (ValidationError, Error, ValueError):
            raise HTTPException(422, "Invalid voice package") from None
        validate_voice(package.voice)
        reference_id = write_reference(audio)
        try:
            return save_voice(Voice(**package.voice.model_dump(), reference=reference_id))
        except Exception:
            (root / "voices" / f"{reference_id}.wav").unlink(missing_ok=True)
            raise

    @app.delete(api + "/voices/{voice_id}")
    def delete_voice(voice_id: UUID):
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("DELETE FROM voices WHERE id = ?", (str(voice_id),))
        return {"id": voice_id}

    @app.get(api + "/references/{reference_id}/audio")
    def reference_audio(reference_id: UUID):
        path = root / "voices" / f"{reference_id}.wav"
        if not path.is_file():
            raise HTTPException(404, "Reference audio missing")
        return FileResponse(path, media_type="audio/wav")

    @app.post(api + "/tasks/{task_id}/cancel")
    async def cancel(task_id: UUID):
        process = active.get(task_id)
        if process is None:
            raise HTTPException(404, "Task is not running")
        if process.is_alive():
            process.terminate()
        return {"id": task_id}

    @app.get(api + "/tasks")
    async def tasks():
        return [{"id": task_id, "status": "running"} for task_id in active]

    @app.get(api + "/workspaces/{kind}")
    def load_workspace(kind: Literal["dialogue", "batch"]):
        with closing(sqlite3.connect(database)) as db:
            row = db.execute("SELECT data FROM workspaces WHERE kind = ?", (kind,)).fetchone()
        return json.loads(row[0]) if row else None

    @app.put(api + "/workspaces/{kind}")
    def save_workspace(kind: Literal["dialogue", "batch"], workspace: Workspace):
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("INSERT OR REPLACE INTO workspaces VALUES (?, ?)", (kind, workspace.model_dump_json()))
        return {"saved": True}

    @app.post(api + "/tts/stream/{task_id}")
    async def stream(task_id: UUID, request: Generation):
        if active:
            raise HTTPException(409, "Another generation is running")
        if request.reference and not (root / "voices" / f"{request.reference}.wav").is_file():
            raise HTTPException(404, "Reference audio missing")
        if not mock and not all(installed(root / "models", name)
                               for name in filenames(request.model, request.quant)):
            raise HTTPException(409, "Install the selected model weights first")
        path = root / "outputs" / f"{task_id}.wav"
        if path.exists():
            raise HTTPException(409, "Task already exists")

        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=infer, args=(sender, root, cache, request.model_dump(), mock),
                                  daemon=True)
        try:
            process.start()
        except Exception:
            receiver.close()
            raise
        finally:
            sender.close()
        active[task_id] = process

        async def events():
            nonlocal confirmed_metal
            temp = path.with_suffix(".part")
            started = time.perf_counter()
            first = None
            count = 0
            rate = 0
            complete = False
            try:
                with wave.open(str(temp), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(24000)
                    while True:
                        try:
                            if not receiver.poll():
                                await asyncio.sleep(0.015)
                                continue
                            sample_rate, chunk = receiver.recv()
                        except (EOFError, OSError):
                            break
                        if sample_rate == 0:
                            complete = True
                            break
                        if not isinstance(sample_rate, int):
                            yield json.dumps({"error": sample_rate}) + "\n"
                            return
                        if first is None:
                            first = time.perf_counter() - started
                            rate = sample_rate
                            audio.setframerate(rate)
                        if sample_rate != rate:
                            yield '{"error":"sample_rate_changed"}\n'
                            return
                        audio.writeframesraw(chunk)
                        count += len(chunk) // 2
                        yield json.dumps({"rate": rate, "pcm": base64.b64encode(chunk).decode()}) + "\n"
                await asyncio.to_thread(process.join, 1)
                if not complete or not count or process.exitcode != 0:
                    yield '{"error":"generation_interrupted"}\n'
                    return
                seconds = time.perf_counter() - started
                record = {"id": str(task_id), "request": request.model_dump(mode="json"),
                          "mock": mock, "created": time.time(), "duration": count / rate,
                          "elapsed": seconds, "ttfa": first, "rtf": seconds * rate / count}
                temp.replace(path)
                try:
                    with closing(sqlite3.connect(database)) as db, db:
                        db.execute("INSERT INTO history VALUES (?, ?)", (str(task_id), json.dumps(record)))
                except Exception:
                    path.unlink(missing_ok=True)
                    raise
                confirmed_metal = not mock
                yield json.dumps({"result": record}) + "\n"
            finally:
                receiver.close()
                if process.is_alive():
                    process.kill()
                process.join()
                process.close()
                active.pop(task_id, None)
                temp.unlink(missing_ok=True)

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @app.get(api + "/history")
    def history():
        with closing(sqlite3.connect(database)) as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM history ORDER BY rowid DESC")]

    @app.delete(api + "/history/{task_id}")
    def delete_history(task_id: UUID):
        with closing(sqlite3.connect(database)) as db, db:
            row = db.execute("SELECT id FROM history WHERE id = ?", (str(task_id),)).fetchone()
            if row is None:
                raise HTTPException(404, "History record missing")
            (root / "outputs" / f"{task_id}.wav").unlink(missing_ok=True)
            db.execute("DELETE FROM history WHERE id = ?", (str(task_id),))
        return {"id": task_id}

    @app.get(api + "/history/{task_id}/audio")
    def audio(task_id: UUID):
        path = root / "outputs" / f"{task_id}.wav"
        if not path.is_file():
            raise HTTPException(404, "Audio missing")
        return FileResponse(path, media_type="audio/wav", filename=path.name)

    @app.post(api + "/exports")
    def export_clips(request: ExportRequest):
        import zipfile

        clips = [(root / "outputs" / f"{clip.id}.wav", clip.pause_ms) for clip in request.clips]
        if any(not path.is_file() for path, _ in clips):
            raise HTTPException(404, "Generated audio missing")
        destination = root / "runtime" / f"{uuid4()}.{request.format}"
        try:
            if request.format == "zip":
                with zipfile.ZipFile(destination, "w", allowZip64=True) as archive:
                    for index, (path, _) in enumerate(clips, 1):
                        archive.write(path, f"{index:02d}-{path.name}")
            else:
                config = None
                with wave.open(str(destination), "wb") as merged:
                    for path, duration in clips:
                        with wave.open(str(path), "rb") as audio:
                            current = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate())
                            if config is None:
                                config = current
                                merged.setnchannels(config[0])
                                merged.setsampwidth(config[1])
                                merged.setframerate(config[2])
                            if current != config:
                                raise HTTPException(422, "Dialogue clips must have matching audio formats")
                            while block := audio.readframes(32768):
                                merged.writeframesraw(block)
                            merged.writeframesraw(bytes(config[0] * config[1] * (duration * config[2] // 1000)))
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        name = "dialogue.wav" if request.format == "wav" else "batch.zip"
        return FileResponse(destination, filename=name,
                            background=BackgroundTask(destination.unlink, missing_ok=True))

    return app


def main():
    import argparse
    import uvicorn
    from fastapi.staticfiles import StaticFiles

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--logs", type=Path)
    parser.add_argument("--web", type=Path, required=True)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--parent", type=int)
    args = parser.parse_args()
    if args.parent:
        import signal

        if args.mock or os.getpgrp() != os.getpid() or os.getppid() != args.parent:
            raise RuntimeError("Invalid desktop backend process group")

        def watch_parent():
            while os.getppid() == args.parent:
                time.sleep(1)
            os.killpg(os.getpgrp(), signal.SIGKILL)

        threading.Thread(target=watch_parent, daemon=True).start()
    token = secrets.token_urlsafe(32)
    app = create_app(args.root, token, args.mock, args.cache, args.logs)

    @app.get("/")
    def index():
        from fastapi.responses import HTMLResponse

        html = (args.web / "index.html").read_text(encoding="utf-8")
        html = html.replace("</head>", f'<meta name="studio-token" content="{token}"></head>')
        return HTMLResponse(html, headers={
            "Cache-Control": "no-store", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; media-src 'self' blob:; "
                                       "style-src 'self' 'unsafe-inline'; connect-src 'self' blob:; "
                                       "frame-ancestors 'none'",
        })

    app.mount("/assets", StaticFiles(directory=args.web / "assets"), name="assets")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        print(f"{port} {token}", flush=True)
        uvicorn.Server(uvicorn.Config(app, access_log=False)).run(sockets=[listener])


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
