"""XDG locations for personal desktop state, independent of the checkout/cwd."""
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class StoragePaths:
    data: Path
    thumbnails: Path
    config: Path


def storage_paths(data_dir=None, cache_dir=None, *, environ=None, home=None):
    env = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)

    def xdg(name, fallback):
        value = env.get(name, "")
        # The XDG specification requires absolute paths; ignore relative values.
        return Path(value) if value and Path(value).is_absolute() else home / fallback

    data = Path(data_dir).expanduser() if data_dir is not None else xdg('XDG_DATA_HOME', '.local/share') / 'image-lab'
    if cache_dir is not None:
        cache = Path(cache_dir).expanduser()
    elif data_dir is not None:
        # Explicit development/test catalogs remain self-contained by default.
        cache = data
    else:
        cache = xdg('XDG_CACHE_HOME', '.cache') / 'image-lab'
    config = xdg('XDG_CONFIG_HOME', '.config') / 'image-lab'
    return StoragePaths(data.resolve(), (cache / 'thumbnails').resolve(), config.resolve())
