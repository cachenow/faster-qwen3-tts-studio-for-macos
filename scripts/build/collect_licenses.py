"""Copy license texts for frontend and Rust packages into the app."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def copy_licenses(source, destination):
    for path in source.iterdir():
        if path.is_file() and re.match(r"^(licen[cs]e|notice|copying)([._-]|$)", path.name, re.I):
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination / path.name)


def main():
    target = Path(sys.argv[1])
    frontend = Path("frontend").resolve()
    packages = subprocess.check_output(
        ["npm", "--prefix", "frontend", "ls", "--omit=dev", "--all", "--parseable"], text=True,
    ).splitlines()
    paths = {Path(path) for path in packages}
    paths.add(frontend / "node_modules" / "tailwindcss")
    for path in sorted(paths):
        if not path.is_relative_to(frontend / "node_modules"):
            continue
        package = json.loads((path / "package.json").read_text(encoding="utf-8"))
        copy_licenses(path, target / "npm" / package["name"] / package["version"])

    metadata = json.loads(subprocess.check_output(
        ["cargo", "metadata", "--locked", "--format-version", "1",
         "--filter-platform", "aarch64-apple-darwin", "--manifest-path", "src-tauri/Cargo.toml"],
        text=True,
    ))
    for package in metadata["packages"]:
        if not package["source"]:
            continue
        source = Path(package["manifest_path"]).parent
        folder = target / "cargo" / package["name"] / package["version"]
        copy_licenses(source, folder)
        if package["license_file"]:
            license_file = source / package["license_file"]
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(license_file, folder / license_file.name)


if __name__ == "__main__":
    main()
