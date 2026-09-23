"""Catalog-local UI preferences; defaults preserve existing playback behavior."""
import json

DEFAULTS = {
    'autoplayViewerGifs': True,
    'autoplaySidebarGifs': True,
    'animateHoveredGifs': True,
}


def load_preferences(db):
    row = db.execute("SELECT value FROM preferences WHERE key='playback'").fetchone()
    try:
        saved = json.loads(row['value']) if row else {}
    except (TypeError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    return {key: saved[key] if isinstance(saved.get(key), bool) else default
            for key, default in DEFAULTS.items()}


def save_preferences(db, values):
    if not isinstance(values, dict) or set(values) != set(DEFAULTS) or not all(isinstance(value, bool) for value in values.values()):
        raise ValueError('Playback settings must be on or off.')
    with db:
        db.execute("INSERT INTO preferences(key,value) VALUES ('playback',?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(values),))
