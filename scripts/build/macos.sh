#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
[[ "$(uname -m)" == arm64 ]]
export MACOSX_DEPLOYMENT_TARGET=14.0
export UV_PYTHON_INSTALL_DIR="$PWD/.local/standalone"
export UV_PYTHON_BIN_DIR="$PWD/.local/bin"
export UV_CACHE_DIR="$PWD/.local/uv-cache"
export CARGO_INCREMENTAL=0
export CARGO_PROFILE_RELEASE_DEBUG=0

npm --prefix frontend ci
npm --prefix frontend run build
uv python install 3.12.12
python_bin="$(uv python find --managed-python 3.12.12)"
python_home="$(dirname "$(dirname "$python_bin")")"
mkdir -p .local/build src-tauri/icons artifacts
python3 scripts/build/icon.py .local/build/icon.iconset
iconutil -c icns .local/build/icon.iconset -o src-tauri/icons/icon.icns
cp .local/build/icon.iconset/icon_128x128.png src-tauri/icons/icon.png
uv lock --check --python "$python_bin"
frontend/node_modules/.bin/tauri build --target aarch64-apple-darwin --bundles app -- --locked

app="$PWD/src-tauri/target/aarch64-apple-darwin/release/bundle/macos/Faster Qwen3-TTS Studio.app"
studio="$app/Contents/Resources/studio"
mkdir -p "$studio"
ditto "$python_home" "$studio/python"
ditto frontend/dist "$studio/web"
ditto backend "$studio/backend"
if [[ -f THIRD_PARTY_NOTICES.md ]]; then
  cp THIRD_PARTY_NOTICES.md "$studio/"
fi
ditto licenses "$studio/licenses"
python3 scripts/build/collect_licenses.py "$studio/licenses"
uv export --frozen --no-dev --extra metal --no-emit-project --format requirements-txt -o .local/build/runtime.txt
uv pip install --python "$studio/python/bin/python3.12" --prefix "$studio/python" \
  --require-hashes --only-binary qwentts-cpp-python --no-deps \
  --python-platform aarch64-apple-darwin -r .local/build/runtime.txt

report="$PWD/artifacts/BUILD-REPORT.txt"
{
  sw_vers
  uname -m
  node --version
  npm --version
  uv --version
  rustc --version
  "$studio/python/bin/python3.12" --version
  echo "Hardware inference validation pending"
} > "$report"
python3 scripts/build/check_macho.py "$app/Contents" "$report"
PYTHONPATH="$studio" "$studio/python/bin/python3.12" -B -c 'import platform, importlib.metadata as m; import fastapi; from backend.upstream_ggml import GGMLQwen3TTS; from qwentts_cpp import QwenLibrary; assert platform.machine() == "arm64"; print(m.version("qwentts-cpp-python"), QwenLibrary().version())' | tee -a "$report"
codesign --force --sign - "$app"
codesign --verify --deep --strict --verbose=2 "$app"

version="$(node -p "require('./src-tauri/tauri.conf.json').version")"
name="Faster-Qwen3-TTS-Studio-v$version-arm64"
staging="$(mktemp -d "$PWD/.local/build/dmg.XXXXXX")"
mount="$(mktemp -d "$PWD/.local/build/mount.XXXXXX")"
trap 'hdiutil detach "$mount" >/dev/null 2>&1 || true' EXIT
ditto "$app" "$staging/$(basename "$app")"
install -m 755 scripts/build/uninstall.command "$staging/Uninstall Studio.command"
ln -s /Applications "$staging/Applications"
hdiutil create -ov -format UDZO -volname 'Faster Qwen3-TTS Studio' -srcfolder "$staging" "artifacts/$name.dmg"
hdiutil attach -nobrowse -readonly -mountpoint "$mount" "artifacts/$name.dmg"
mounted="$mount/$(basename "$app")"
codesign --verify --deep --strict --verbose=2 "$mounted"
STUDIO_SMOKE_TEST=1 python3 - "$mounted/Contents/MacOS/faster-qwen3-tts-studio" <<'PY' | tee -a "$report"
import subprocess
import sys
subprocess.run([sys.argv[1]], timeout=60, check=True)
PY
test -x "$mount/Uninstall Studio.command"
/bin/bash "$mount/Uninstall Studio.command" --list >> "$report"
hdiutil detach "$mount"
ditto -c -k --keepParent "$app" "artifacts/$name.app.zip"
{
  echo 'Download sizes in bytes (DMG and alternative App ZIP):'
  wc -c "artifacts/$name.dmg" "artifacts/$name.app.zip"
  echo 'Installed disk usage (App, bundled Python):'
  du -sh "$app" "$studio/python"
  echo 'Largest Python package entries (KiB):'
  du -sk "$studio/python/lib/python3.12/site-packages/"* | sort -nr | sed -n '1,10p'
} | tee -a "$report"
cp src-tauri/Cargo.lock artifacts/Cargo.lock
cp uv.lock artifacts/uv.lock
(cd artifacts && shasum -a 256 "$name.dmg" "$name.app.zip" > SHA256SUMS.txt)
