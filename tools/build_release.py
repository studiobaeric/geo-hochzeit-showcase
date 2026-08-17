#!/usr/bin/env python3
"""Build a standalone executable for the current OS with PyInstaller.

Used by .github/workflows/release.yml (once per OS in a build matrix) to
produce the binaries attached to a GitHub Release. Can also be run locally
to try out a packaged build before tagging a release:

    pip install -r requirements-build.txt
    python tools/build_release.py --version dev

The result is a folder (and matching archive) under dist/ containing the
executable plus the templates/ and static/ folders it needs at runtime -
see app.py's frozen-path handling. The offline basemap (static/data/
basemap.pmtiles) and glyph fonts (static/fonts/) are intentionally left
out: they are large, environment-specific, and already excluded from git
(see README.md's "Offline-Karte (PMTiles) bauen" section for how to add
them to a build after unpacking it).
"""

import argparse
import pathlib
import platform
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_NAME = "kartenquiz"

OS_NAMES = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}

PACKAGE_README = """\
Kartenquiz {version} ({os_name})
=================================

Start:
  - Windows: Doppelklick auf {exe_name}
  - macOS/Linux: ./{exe_name}  (im Terminal, aus diesem Ordner heraus)

Der Browser oeffnet sich automatisch auf http://localhost:8080. Andere
Geraete im selben WLAN erreichen das Spiel ueber die IP dieses Rechners,
z.B. http://192.168.1.23:8080.

Offline-Karte hinzufuegen (optional):
  Diese Binaries enthalten keine Kartendaten (zu gross fuer ein
  automatisches Release-Build). Um die Offline-Karte zu nutzen, folge den
  Schritten unter "Offline-Karte (PMTiles) bauen" in der README des
  Projekts (https://github.com/n1c01/Geo_Hochzeit) und kopiere das
  Ergebnis nach static/data/basemap.pmtiles bzw. static/fonts/ in diesem
  Ordner.

Eigene Fotos & Namen:
  Siehe static/config/README.md in diesem Ordner.
"""


def _archive_format() -> str:
    return "zip" if platform.system() == "Windows" else "gztar"


def build(version: str) -> pathlib.Path:
    dist = ROOT / "dist"
    build_dir = ROOT / "build"
    shutil.rmtree(dist, ignore_errors=True)
    shutil.rmtree(build_dir, ignore_errors=True)

    bin_dir = dist / "bin"
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--name", APP_NAME,
            "--distpath", str(bin_dir),
            "--workpath", str(build_dir),
            "--specpath", str(build_dir),
            str(ROOT / "app.py"),
        ],
        check=True,
        cwd=ROOT,
    )

    os_name = OS_NAMES.get(platform.system(), platform.system().lower())
    package_dir = dist / f"{APP_NAME}-{os_name}"
    package_dir.mkdir(parents=True, exist_ok=True)

    exe_name = f"{APP_NAME}.exe" if platform.system() == "Windows" else APP_NAME
    shutil.move(str(bin_dir / exe_name), str(package_dir / exe_name))
    if platform.system() != "Windows":
        (package_dir / exe_name).chmod(0o755)

    shutil.copytree(ROOT / "templates", package_dir / "templates")
    shutil.copytree(
        ROOT / "static", package_dir / "static",
        ignore=shutil.ignore_patterns("*.pmtiles"),
    )
    (package_dir / "data").mkdir(exist_ok=True)
    (package_dir / "VERSION").write_text(version + "\n", encoding="utf-8")
    (package_dir / "README.txt").write_text(
        PACKAGE_README.format(version=version, os_name=os_name, exe_name=exe_name),
        encoding="utf-8",
    )

    archive_path = shutil.make_archive(
        str(dist / f"{APP_NAME}-{os_name}"),
        _archive_format(),
        root_dir=dist,
        base_dir=package_dir.name,
    )
    return pathlib.Path(archive_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version", default="dev",
        help="Version string written into the package's VERSION file (e.g. a git tag).",
    )
    args = parser.parse_args()

    archive = build(args.version)
    print(f"Built {archive}")


if __name__ == "__main__":
    main()
