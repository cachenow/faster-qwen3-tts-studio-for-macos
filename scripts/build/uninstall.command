#!/bin/bash
set -e
# Bundled on the read-only DMG; operate only on this product in the current account.
[[ "$(uname -s)" == Darwin && "$(/usr/bin/id -u)" != 0 ]] || { echo "Run as the signed-in macOS user."; exit 1; }
bundle=studio.fasterqwen3tts.desktop
product=FasterQwen3TTSStudio
home_dir="$(cd "$HOME" && pwd -P)"
[[ -n "$home_dir" && "$home_dir" != / ]] || exit 1
targets=()
add_target() {
  local path="$1" parent
  [[ -e "$path" || -L "$path" ]] || return 0
  parent="$(cd "$(dirname "$path")" && pwd -P)"
  [[ "$parent" == "$(dirname "$path")" ]] || { echo "Unexpected linked parent: $path"; exit 1; }
  targets+=("$path")
}
for folder in 'Application Support' Caches Logs; do
  add_target "$home_dir/Library/$folder/$product"
done
for folder in 'Application Support' Caches Logs WebKit HTTPStorages; do
  add_target "$home_dir/Library/$folder/$bundle"
done
add_target "$home_dir/Library/HTTPStorages/$bundle.binarycookies"
add_target "$home_dir/Library/Cookies/$bundle.binarycookies"
add_target "$home_dir/Library/Preferences/$bundle.plist"
add_target "$home_dir/Library/Saved Application State/$bundle.savedState"
for folder in /Applications "$home_dir/Applications"; do
  path="$folder/Faster Qwen3-TTS Studio.app"
  if [[ -d "$path" && ! -L "$path" ]] && [[ "$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$path/Contents/Info.plist")" == "$bundle" ]]; then
    add_target "$path"
  fi
done
if [[ ${#targets[@]} == 0 ]]; then echo "未找到安装文件 / No installation files found."; exit 0; fi
printf '将永久删除 / Permanently remove:\n'
printf '  %s\n' "${targets[@]}"
[[ "${1:-}" != --list ]] || exit 0
if /usr/bin/pgrep -f '[.]app/Contents/MacOS/faster-qwen3-tts-studio' >/dev/null; then
  echo '请先退出 Studio / Quit Studio first.'; exit 1
fi
echo '如将 App 放在其他位置，请自行移到废纸篓。 / Move any custom-location app to Trash yourself.'
read -r -p '输入 DELETE 确认 / Type DELETE to confirm: ' answer
[[ "$answer" == DELETE ]] || exit 0
# Ask the preferences daemon to forget this app domain before removing its file.
if /usr/bin/defaults read "$bundle" >/dev/null 2>&1; then
  /usr/bin/defaults delete "$bundle"
fi
for path in "${targets[@]}"; do
  /bin/rm -rf -- "$path"
done
echo '清理完成 / Cleanup complete.'
