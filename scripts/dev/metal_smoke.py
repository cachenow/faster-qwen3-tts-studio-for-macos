"""Run a focused Metal test with matching local GGUF weights."""
import argparse
import os
import platform
import time
import wave
from pathlib import Path

from backend.engine import MetalEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("talker", type=Path)
    parser.add_argument("codec", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--speaker", default="Vivian")
    parser.add_argument("--text", default="Hello from Apple Silicon.")
    parser.add_argument("--language", default="English")
    args = parser.parse_args()
    engine = MetalEngine(args.output.parent / "reference-cache")
    started = time.perf_counter()
    count = 0
    with wave.open(str(args.output), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        for rate, pcm in engine.stream("custom-smoke", args.talker, args.codec,
                                      args.text, args.language, "custom", speaker=args.speaker):
            if count == 0:
                target.setframerate(rate)
                print(f"TTFA: {time.perf_counter() - started:.3f}s")
            target.writeframesraw(pcm)
            count += len(pcm)
    if not count:
        raise SystemExit("Model returned no samples")
    print(f"{platform.platform()} {os.environ['GGML_BACKEND']} PCM bytes: {count}")


if __name__ == "__main__":
    main()
