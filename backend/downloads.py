import asyncio
import hashlib
import json
from pathlib import Path

import httpx

CATALOG = json.loads(Path(__file__).with_name("weights.json").read_text(encoding="utf8"))
SOURCES = {"official": "https://huggingface.co", "mirror": "https://hf-mirror.com"}


async def download_weight(directory: Path, name: str, progress, source: str):
    """Publish only complete GGUFs that match the pinned LFS object."""
    if installed(directory, name):
        return
    final = directory / name
    partial = final.with_suffix(".part")
    entry = CATALOG["files"][name]
    length, digest = entry["bytes"], entry["sha256"]
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > length:
        partial.unlink()
        offset = 0
    progress(name, offset, length)
    if offset < length:
        url = f"{SOURCES[source]}/Serveurperso/Qwen3-TTS-GGUF/resolve/{CATALOG['revision']}/{name}"
        headers = {"Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30, connect=12)) as client:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code == 200:
                    offset = 0
                elif response.status_code != 206:
                    raise ValueError(f"HTTP {response.status_code} · {name}")
                elif response.headers.get("Content-Range") != f"bytes {offset}-{length - 1}/{length}":
                    raise ValueError("Invalid model byte range")
                with partial.open("ab" if offset else "wb") as output:
                    async for chunk in response.aiter_bytes(256 * 1024):
                        offset += len(chunk)
                        if offset > length:
                            raise ValueError("Model response exceeds expected size")
                        output.write(chunk)
                        progress(name, offset, length)
    if partial.stat().st_size != length:
        raise ValueError("Model download interrupted")
    actual = hashlib.sha256()
    with partial.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            actual.update(chunk)
            await asyncio.sleep(0)
    if actual.hexdigest() != digest:
        partial.unlink()
        raise ValueError("Model integrity check failed")
    partial.replace(final)
    final.with_suffix(".verified").write_text(f"{length} {digest}", encoding="ascii")


def installed(directory, name):
    path = directory / name
    try:
        length, digest = path.with_suffix(".verified").read_text(encoding="ascii").split()
        pinned = CATALOG["files"][name]
        return path.stat().st_size == int(length) == pinned["bytes"] and digest == pinned["sha256"]
    except (OSError, ValueError, KeyError):
        return False
