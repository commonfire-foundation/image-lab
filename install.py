"""Install the Image Lab release bundle into an isolated user environment.

Run `python3 install.py` from the extracted bundle. No sudo, system package
changes, or source checkout is needed. Pass --dry-run to inspect the targets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


class InstallError(Exception):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bundle_files(bundle: Path) -> dict:
    try:
        manifest = json.loads((bundle / "release.json").read_text(encoding="utf-8"))
        if manifest["schema"] != 2 or manifest["app_version"] != "0.1.0":
            raise InstallError("Unsupported release manifest")
        if manifest["imagescope_version"] != "0.1.0rc2":
            raise InstallError("Unsupported Imagescope version")
        expected = {"image_lab": f"image_lab-{manifest['app_version']}-py3-none-any.whl",
                    "imagescope": f"imagescope-{manifest['imagescope_version']}-py3-none-any.whl"}
        if manifest["wheels"] != expected:
            raise InstallError("Unexpected wheel names in release manifest")
        source_name = "imagescope-0.1.0rc2.tar.gz"
        if (manifest["provider_source"]["archive"] != source_name
                or not isinstance(manifest["provider_source"]["base_ref"], str)
                or not manifest["provider_source"]["base_ref"]):
            raise InstallError("Missing Imagescope source provenance")
        required = set(expected.values()) | {"install.py", "LICENSE", "image-lab.svg", source_name}
        if set(manifest["sha256"]) != required:
            raise InstallError("Incomplete release manifest")
        for name, digest in manifest["sha256"].items():
            if not isinstance(digest, str) or len(digest) != 64 or sha256(bundle / name) != digest:
                raise InstallError(f"Bundle checksum mismatch: {name}")
        return manifest
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
        raise InstallError(f"Invalid release bundle: {error}") from error


def entry_exec(path: Path) -> str:
    # Desktop Entry Exec quoting for a command with no user-supplied arguments.
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`").replace("%", "%%") + '"'


def desktop_entry(bin_dir: Path, icon: Path) -> str:
    return ("[Desktop Entry]\nType=Application\nName=Image Lab\n"
            f"Exec={entry_exec(bin_dir / 'image-lab-ui')}\n"
            f"Icon={icon}\nTerminal=false\nCategories=Graphics;\n")


def run(command: list[str], log: Path, env: dict[str, str]) -> None:
    with log.open("a", encoding="utf-8") as output:
        output.write("$ " + " ".join(command) + "\n")
        output.flush()
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, env=env, check=False)
    if result.returncode:
        details = log.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
        raise InstallError("Package installation failed:\n" + "\n".join(details))


def install_environment(destination: Path, bundle: Path, manifest: dict, offline: bool) -> None:
    python = destination / "venv" / "bin" / "python"
    log = destination / "install.log"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    provider = bundle / manifest["wheels"]["imagescope"]
    app = bundle / manifest["wheels"]["image_lab"]
    uv = shutil.which("uv")
    print("Installing in an isolated user environment…", flush=True)
    if uv:
        run([uv, "venv", "--python", sys.executable, str(destination / "venv")], log, env)
        manager = [uv, "pip", "install", "--python", str(python)]
        check = [uv, "pip", "check", "--python", str(python)]
    else:
        run([sys.executable, "-m", "venv", str(destination / "venv")], log, env)
        if subprocess.run([str(python), "-m", "pip", "--version"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, env=env, check=False).returncode != 0:
            raise InstallError("This Python venv has no pip. Install uv and run the installer again.")
        manager = [str(python), "-m", "pip", "install"]
        check = [str(python), "-m", "pip", "check"]
    # Install the supplied provider first, then resolve the app and all of its
    # dependencies normally. Never substitute another wheel with the same label.
    run(manager + ["--no-deps", str(provider)], log, env)
    options = ["--no-index"] if offline else []
    run(manager + options + ["--find-links", str(bundle), str(app) + "[desktop]"], log, env)
    run(check, log, env)
    run([str(python), "-c", "import image_lab_ui.app, imagescope; "
         "from importlib.metadata import version; "
         "assert version('image-lab') == '0.1.0'; "
         "assert version('imagescope') == '0.1.0rc2'; "
         "assert hasattr(imagescope, 'inspect_metadata')"], log, env)
    (destination / "receipt.json").write_text(json.dumps({"sha256": manifest["sha256"]}, indent=2) + "\n",
                                               encoding="utf-8")
    shutil.copyfile(bundle / "image-lab.svg", destination / "image-lab.svg")


def verify_targets(links: dict[Path, Path], desktop: Path | None, text: str, replace: bool) -> None:
    for link, target in links.items():
        if link.exists() or link.is_symlink():
            if not link.is_symlink():
                raise InstallError(f"Not replacing a non-symlink command: {link}")
            if link.resolve() != target.resolve() and not replace:
                raise InstallError(f"Existing command: {link}. Re-run with --replace-existing to back it up.")
    if desktop and (desktop.exists() or desktop.is_symlink()):
        if desktop.is_symlink() or not desktop.is_file():
            raise InstallError(f"Not replacing an unusual desktop entry: {desktop}")
        if desktop.read_text(encoding="utf-8") != text and not replace:
            raise InstallError(f"Existing desktop entry: {desktop}. Re-run with --replace-existing to back it up.")


def activate(destination: Path, links: dict[Path, Path], desktop: Path | None, text: str) -> None:
    old_links = {link: os.readlink(link) if link.is_symlink() else None for link in links}
    old_desktop = desktop.read_bytes() if desktop and desktop.exists() else None
    backup = {str(path): value for path, value in old_links.items() if value is not None}
    saved_links = destination / "previous-launchers.json"
    if not saved_links.exists():
        saved_links.write_text(json.dumps(backup, indent=2) + "\n", encoding="utf-8")
    saved_desktop = destination / "previous-image-lab.desktop"
    if old_desktop is not None and not saved_desktop.exists():
        saved_desktop.write_bytes(old_desktop)
    changed = []
    try:
        for link, target in links.items():
            link.parent.mkdir(parents=True, exist_ok=True)
            temp = link.with_name(f".{link.name}.{os.getpid()}.new")
            temp.symlink_to(target)
            try:
                temp.replace(link)
            finally:
                temp.unlink(missing_ok=True)
            changed.append(link)
        if desktop:
            desktop.parent.mkdir(parents=True, exist_ok=True)
            temp = desktop.with_name(f".{desktop.name}.{os.getpid()}.new")
            temp.write_text(text, encoding="utf-8")
            try:
                temp.replace(desktop)
            finally:
                temp.unlink(missing_ok=True)
            changed.append(desktop)
    except OSError:
        for path in reversed(changed):
            if path == desktop:
                if old_desktop is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(old_desktop)
            elif old_links[path] is None:
                path.unlink(missing_ok=True)
            else:
                temp = path.with_name(f".{path.name}.{os.getpid()}.restore")
                temp.symlink_to(old_links[path])
                temp.replace(path)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")).expanduser()
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent,
                        help="Directory containing release.json and the tested wheels")
    parser.add_argument("--install-root", type=Path, default=default_data / "image-lab")
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin")
    parser.add_argument("--desktop-dir", type=Path, default=default_data / "applications")
    parser.add_argument("--no-desktop", action="store_true", help="Do not add an application-menu entry")
    parser.add_argument("--replace-existing", action="store_true", help="Back up and replace existing command links")
    parser.add_argument("--offline", action="store_true", help="Require all dependencies in the local bundle/cache")
    parser.add_argument("--dry-run", action="store_true", help="Check the bundle and show targets without installing")
    args = parser.parse_args()
    try:
        if sys.platform != "linux" or sys.version_info < (3, 11):
            raise InstallError("Image Lab needs Linux and Python 3.11 or later")
        bundle = args.bundle.expanduser().resolve(strict=True)
        manifest = bundle_files(bundle)
        root = args.install_root.expanduser().absolute()
        bin_dir = args.bin_dir.expanduser().absolute()
        desktop_dir = args.desktop_dir.expanduser().absolute()
        for path in (root, bin_dir, desktop_dir):
            if path.is_symlink():
                raise InstallError(f"Install directory must not be a symlink: {path}")
        identity = (manifest["sha256"][manifest["wheels"]["image_lab"]][:12] + "-" +
                    manifest["sha256"][manifest["wheels"]["imagescope"]][:12])
        destination = root / (manifest["app_version"] + "-" + identity)
        links = {bin_dir / name: destination / "venv" / "bin" / name
                 for name in ("image-lab", "image-lab-ui", "imagescope")}
        desktop = None if args.no_desktop else desktop_dir / "image-lab.desktop"
        text = desktop_entry(bin_dir, destination / "image-lab.svg")
        verify_targets(links, desktop, text, args.replace_existing)
        print(f"Image Lab {manifest['app_version']} + Imagescope {manifest['imagescope_version']}")
        print(f"Install: {destination}\nCommands: {bin_dir}\nDesktop entry: {desktop or 'skipped'}")
        if args.dry_run:
            print("Dry run: nothing changed.")
            return
        root.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not (destination / "receipt.json").is_file():
                raise InstallError(f"Install target already exists but is incomplete: {destination}")
            receipt = json.loads((destination / "receipt.json").read_text(encoding="utf-8"))
            if receipt.get("sha256") != manifest["sha256"]:
                raise InstallError(f"Install target has different contents: {destination}")
            print("Matching installation already present; checking commands.")
        else:
            destination.mkdir()
            try:
                install_environment(destination, bundle, manifest, args.offline)
            except Exception:
                shutil.rmtree(destination)
                raise
        verify_targets(links, desktop, text, args.replace_existing)
        activate(destination, links, desktop, text)
        print("Installed. Start with image-lab-ui (or choose Image Lab from the app menu).")
    except (InstallError, OSError, subprocess.SubprocessError, ValueError) as error:
        parser.exit(1, f"Install failed: {error}\n")


if __name__ == "__main__":
    main()
