"""Isolate changes to the GGML API from Studio's service layer."""
import math
import os
import platform
import struct
import time
from pathlib import Path


class MetalEngine:
    def __init__(self, cache: Path):
        self.cache = cache
        self.key = None
        self.model = None

    def unload(self):
        model, self.model = self.model, None
        self.key = None
        if model is not None:
            model.runtime.close()

    def stream(self, model_id, talker, codec, text, language, mode, **options):
        if platform.system() != "Darwin" or platform.machine() != "arm64":
            raise RuntimeError("Metal requires native macOS ARM64")
        os.environ["GGML_BACKEND"] = "MTL0"
        os.environ["HF_HUB_OFFLINE"] = "1"
        from .upstream_ggml import GGMLQwen3TTS

        key = (model_id, talker, codec)
        if self.key != key:
            self.unload()
            self.cache.mkdir(parents=True, exist_ok=True)
            os.environ["FQWEN3TTS_QWENTTS_REF_CACHE_DIR"] = str(self.cache)
            self.model = GGMLQwen3TTS.from_gguf(talker, codec, voice_ref_cache_dir=self.cache)
            self.key = key

        method = {
            "clone": self.model.generate_voice_clone_streaming,
            "custom": self.model.generate_custom_voice_streaming,
            "design": self.model.generate_voice_design_streaming,
        }[mode]
        import numpy as np

        for wave, rate, _ in method(text=text, language=language, **options):
            pcm = (np.clip(wave, -1, 1) * 32767).astype("<i2")
            yield int(rate), pcm.tobytes()


class MockEngine:
    """Development-only audible test signal."""
    def unload(self):
        pass

    def stream(self, model_id, talker, codec, text, language, mode, **options):
        rate = 24000
        block = struct.pack("<2400h", *(
            round(1100 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(2400)
        ))
        for _ in range(min(40, max(8, len(text) // 3))):
            time.sleep(0.05)
            yield rate, block
