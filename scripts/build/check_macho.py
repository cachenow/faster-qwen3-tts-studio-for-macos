"""Verify and relocate native dependencies before signing the app."""
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

MACH_O_MAGIC = {
    bytes.fromhex(value) for value in (
        "feedface", "cefaedfe", "feedfacf", "cffaedfe",
        "cafebabe", "bebafeca", "cafebabf", "bfbafeca",
    )
}


def output(*args):
    return subprocess.check_output(args, text=True)


def allowed(path):
    return path.startswith(("@rpath/", "@loader_path/", "@executable_path/", "/usr/lib/", "/System/Library/"))


def main():
    contents, report_file = map(Path, sys.argv[1:])
    native = []
    by_name = defaultdict(set)
    for path in contents.rglob("*"):
        if not path.is_file():
            continue
        with path.open("rb") as stream:
            if stream.read(4) not in MACH_O_MAGIC:
                continue
        description = output("file", "-bL", path)
        if "Mach-O" not in description:
            continue
        destination = path.resolve()
        if not destination.is_relative_to(contents.resolve()):
            raise SystemExit(f"Native symlink targets a file outside the app: {path}")
        by_name[path.name].add(destination)
        if not path.is_symlink():
            native.append((path, description))

    with report_file.open("a", encoding="utf-8") as report:
        for path, description in native:
            subprocess.run(["lipo", path, "-verify_arch", "arm64"], check=True)
            target = output("vtool", "-arch", "arm64", "-show-build", path)
            versions = re.findall(r"\b(?:minos|version)\s+(\d+(?:\.\d+)+)", target)
            if not versions or any(tuple(map(int, item.split("."))) > (14, 0, 0) for item in versions):
                raise SystemExit(f"Incompatible deployment target for {path}:\n{target}")

            load_commands = output("otool", "-arch", "arm64", "-L", path).splitlines()[1:]
            identities = []
            if "dynamically linked shared library" in description:
                identities = output("otool", "-arch", "arm64", "-D", path).splitlines()[1:]
            identity = identities[0].strip() if identities else None
            for command in load_commands:
                dependency = command.strip().split(" (compatibility version", 1)[0]
                if dependency == identity or allowed(dependency):
                    continue
                matches = by_name[Path(dependency).name]
                if len(matches) != 1:
                    raise SystemExit(f"Cannot uniquely relocate {dependency} referenced by {path}")
                replacement = "@loader_path/" + os.path.relpath(next(iter(matches)), path.parent)
                subprocess.run(["install_name_tool", "-change", dependency, replacement, path], check=True)
                report.write(f"Rewrote {dependency} as {replacement} in {path.name}\n")
            if identity and not allowed(identity):
                subprocess.run(["install_name_tool", "-id", "@rpath/" + path.name, path], check=True)
            report.write(output("otool", "-arch", "arm64", "-L", path))

    for path, _ in native:
        subprocess.run(["codesign", "--force", "--sign", "-", path], check=True)


if __name__ == "__main__":
    main()
