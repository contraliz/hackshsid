"""Create a self-bootstrapping macOS ZIP from the current GridShift sources."""

from __future__ import annotations

import hashlib
import shutil
import stat
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "releases"
PACKAGE_NAME = "GridShift-macOS"
STAGE = RELEASES / PACKAGE_NAME
ARCHIVE = RELEASES / f"{PACKAGE_NAME}.zip"

INCLUDE_FILES = (
    "GridShift.command",
    "README-Run-macOS.txt",
    "launcher_macos.py",
    "requirements-macos.txt",
    "server.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    if not (ROOT / "web" / "dist" / "index.html").is_file():
        raise SystemExit("web/dist/index.html is missing; run npm run build first.")
    if not (ROOT / "backend" / "dynamic_simulation.py").is_file():
        raise SystemExit("GridShift backend sources are incomplete.")

    RELEASES.mkdir(exist_ok=True)
    STAGE.mkdir(exist_ok=True)
    for relative in INCLUDE_FILES:
        source = ROOT / relative
        if not source.is_file():
            raise SystemExit(f"Required package file is missing: {relative}")
        shutil.copy2(source, STAGE / relative)

    for directory in ("backend", "web/dist"):
        source = ROOT / directory
        destination = STAGE / directory
        shutil.copytree(
            source,
            destination,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for source in sorted(STAGE.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(RELEASES).as_posix()
            info = zipfile.ZipInfo(relative)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            mode = 0o755 if source.name == "GridShift.command" else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, source.read_bytes())

    with zipfile.ZipFile(ARCHIVE) as archive:
        names = set(archive.namelist())
        required = {
            f"{PACKAGE_NAME}/GridShift.command",
            f"{PACKAGE_NAME}/README-Run-macOS.txt",
            f"{PACKAGE_NAME}/web/dist/index.html",
            f"{PACKAGE_NAME}/backend/dynamic_simulation.py",
        }
        missing = required - names
        if missing:
            raise SystemExit(f"Archive verification failed; missing: {sorted(missing)}")
        command_info = archive.getinfo(f"{PACKAGE_NAME}/GridShift.command")
        if (command_info.external_attr >> 16) & 0o111 != 0o111:
            raise SystemExit("Archive verification failed; GridShift.command is not executable.")

    print(f"macOS launch package: {ARCHIVE}")
    print(f"Size: {ARCHIVE.stat().st_size:,} bytes")
    print(f"SHA-256: {sha256(ARCHIVE)}")
    print("Archive contents and executable launcher permissions verified.")


if __name__ == "__main__":
    main()
