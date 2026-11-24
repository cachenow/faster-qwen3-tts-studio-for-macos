import hashlib
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import certifi

REPOSITORY = "https://huggingface.co/Serveurperso/Qwen3-TTS-GGUF/resolve/b7ee2e8"


class DownloadPaused(Exception):
    pass


def download_weight(directory: Path, name: str, progress, paused):
    """Verify the repository's LFS content digest before publishing a weight."""
    final = directory / name
    receipt = final.with_suffix(".verified")
    if installed(directory, name):
        return
    partial = final.with_suffix(".part")
    url = f"{REPOSITORY}/{name}"
    metadata = urllib.request.Request(url, method="HEAD")
    # Inspect the original redirect response for the Git LFS metadata.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    tls = ssl.create_default_context(cafile=certifi.where())
    try:
        opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=tls))
        with opener.open(metadata, timeout=30) as response:
            headers = response.headers
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise
        headers = e.headers
        e.close()
    digest = headers.get("x-linked-etag", "").strip('"')
    length = int(headers.get("x-linked-size", "0"))
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or length <= 0:
        raise ValueError("Model source did not return a valid LFS digest")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > length:
        partial.unlink()
        offset = 0
    progress(name, offset, length)
    if paused.is_set():
        raise DownloadPaused
    if offset < length:
        request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
        with urllib.request.urlopen(request, timeout=60, context=tls) as response:
            if response.status == 200:
                offset = 0
            elif response.status != 206 or response.headers.get("Content-Range") != f"bytes {offset}-{length - 1}/{length}":
                raise ValueError("Invalid model byte range")
            with partial.open("ab" if offset else "wb") as output:
                while chunk := response.read(1024 * 1024):
                    offset += len(chunk)
                    if offset > length:
                        raise ValueError("Model response exceeds expected size")
                    output.write(chunk)
                    progress(name, offset, length)
                    if paused.is_set():
                        raise DownloadPaused
    if partial.stat().st_size != length:
        raise ValueError("Model download interrupted")
    with partial.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest:
        partial.unlink()
        raise ValueError("Model integrity check failed")
    partial.replace(final)
    receipt.write_text(f"{length} {digest}", encoding="ascii")


def installed(directory, name):
    path = directory / name
    try:
        length, digest = path.with_suffix(".verified").read_text(encoding="ascii").split()
        return path.stat().st_size == int(length) and bool(re.fullmatch(r"[0-9a-f]{64}", digest))
    except (OSError, ValueError):
        return False
