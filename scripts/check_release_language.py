"""Reject CJK text in release-facing files before publishing Parallax Lab."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git",
    ".hypothesis",
    ".next",
    ".pytest_cache",
    ".runtime",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "playwright-report",
    "test-results",
}
EXCLUDED_FILES = {
    "bun.lock",
    "bun.lockb",
    "package-lock.json",
    "Pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "yarn.lock",
}
CJK = re.compile(
    "[\u2e80-\u303f\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf"
    "\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff01-\uff9f"
    "\U00020000-\U0002fa1f]"
)


def candidate_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        check=True,
    )
    paths = {Path(name.decode("utf-8")) for name in result.stdout.split(b"\0") if name}
    return sorted(
        path
        for path in paths
        if not any(part in EXCLUDED_DIRS for part in path.parts)
        and path.name not in EXCLUDED_FILES
        and not path.name.endswith((".min.js", ".min.css", ".map"))
    )


def main() -> int:
    findings = 0
    for relative_path in candidate_files():
        path = ROOT / relative_path
        if not path.is_file() or path.is_symlink():
            continue
        contents = path.read_bytes()
        if b"\0" in contents:
            continue
        try:
            lines = contents.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            continue  # Binary assets are not release copy.
        for number, line in enumerate(lines, start=1):
            if CJK.search(line):
                print(f"{relative_path}:{number}: contains CJK text")
                findings += 1

    if findings:
        print(f"Found {findings} line(s) of CJK text. Use Canadian English in published files.")
        return 1
    print("Release language check passed: no CJK text detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
