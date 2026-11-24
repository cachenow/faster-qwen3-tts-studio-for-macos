"""Generate the Studio waveform mark as a macOS iconset."""
import math
import struct
import sys
import zlib
from pathlib import Path


def chunk(tag, data):
    return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data))


def png(size):
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            u, v = (x + 0.5) / size, (y + 0.5) / size
            corner = math.hypot(max(0, abs(u - 0.5) - 0.30), max(0, abs(v - 0.5) - 0.30))
            color = (0, 0, 0, 0) if corner > 0.16 else (66, 44, 149, 255)
            for index, height in enumerate((0.10, 0.18, 0.29, 0.19, 0.12)):
                dx = abs(u - (0.30 + index * 0.10))
                dy = max(0, abs(v - 0.5) - height + 0.027)
                if math.hypot(dx, dy) < 0.027:
                    color = (242, 235, 255, 255)
            pixels.extend(color)
    header = struct.pack("!2I5B", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


directory = Path(sys.argv[1])
directory.mkdir(parents=True, exist_ok=True)
for base in (16, 32, 128, 256, 512):
    for scale, suffix in ((1, ""), (2, "@2x")):
        (directory / f"icon_{base}x{base}{suffix}.png").write_bytes(png(base * scale))
