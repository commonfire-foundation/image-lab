"""Assemble published Imagescope artifacts and the tested Image Lab wheel.

This reads the separately released provider wheel and source archive without
building or modifying Imagescope. The bundle is not itself a publication.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
APP_VERSION = "0.1.0"
PROVIDER_VERSION = "0.1.0rc2"


def metadata(wheel: Path) -> str:
    with ZipFile(wheel) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"Invalid wheel: {wheel}")
        members = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(members) != 1:
            raise ValueError(f"Missing or ambiguous wheel metadata: {wheel}")
        return archive.read(members[0]).decode("utf-8")


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imagescope-wheel", type=Path, required=True,
                        help="Published Imagescope 0.1.0rc2 wheel")
    parser.add_argument("--imagescope-source-archive", type=Path, required=True,
                        help="Published Imagescope 0.1.0rc2 source archive")
    parser.add_argument("--imagescope-ref", required=True,
                        help="Full commit hash of the published Imagescope release tag")
    parser.add_argument("--image-lab-wheel", type=Path,
                        default=ROOT / "dist" / f"image_lab-{APP_VERSION}-py3-none-any.whl")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "results" / "release-bundles" / f"image-lab-{APP_VERSION}")
    args = parser.parse_args()
    provider = args.imagescope_wheel.resolve(strict=True)
    app = args.image_lab_wheel.resolve(strict=True)
    expected = ((app, "Name: image-lab", f"Version: {APP_VERSION}"),
                (provider, "Name: imagescope", f"Version: {PROVIDER_VERSION}"))
    for wheel, name, version in expected:
        lines = metadata(wheel).splitlines()
        if wheel.suffix != ".whl" or name not in lines or version not in lines:
            parser.error(f"Not the expected release wheel: {wheel}")
    if f"Requires-Dist: imagescope=={PROVIDER_VERSION}" not in metadata(app).splitlines():
        parser.error("Image Lab does not pin the bundled Imagescope version")
    source_archive = args.imagescope_source_archive.resolve(strict=True)
    source_name = f"imagescope-{PROVIDER_VERSION}.tar.gz"
    if source_archive.name != source_name or not source_archive.is_file():
        parser.error(f"Expected published provider source archive: {source_name}")
    if len(args.imagescope_ref) != 40 or any(char not in '0123456789abcdef' for char in args.imagescope_ref):
        parser.error("Imagescope ref must be a full 40-character commit hash")
    output = args.output.resolve()
    archive_path = output.parent / (output.name + ".tar.gz")
    if output.exists() or output.is_symlink() or archive_path.exists():
        parser.error(f"Output already exists; choose a new directory: {output}")
    output.mkdir(parents=True)
    files = (app, provider, source_archive, ROOT / "install.py", ROOT / "LICENSE", ROOT / "image_lab_ui/assets/commonfire-logo.svg")
    entries = {}
    for source in files:
        name = "image-lab.svg" if source.suffix == ".svg" else source.name
        destination = output / name
        shutil.copyfile(source, destination)
        entries[name] = digest(destination)
    manifest = {"schema": 2, "app_version": APP_VERSION,
                "imagescope_version": PROVIDER_VERSION,
                "wheels": {"image_lab": app.name, "imagescope": provider.name},
                "provider_source": {"archive": source_name, "base_ref": args.imagescope_ref,
                                    "note": "Published Imagescope release source archive"},
                "sha256": entries}
    (output / "release.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(output, arcname=output.name)
    print(f"Bundle ready: {archive_path}")
    print(f"SHA-256: {digest(archive_path)}")
    print("After extraction, run: python3 " + str(output / "install.py") + " --dry-run")


if __name__ == "__main__":
    main()
