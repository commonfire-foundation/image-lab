"""Human corrections overlay saved model output without rewriting provenance."""
import hashlib
import json


DEFAULTS = {'caption': '', 'tags': [], 'medium': '', 'mood': [], 'composition': [],
            'text_present': False, 'watermark_present': False}


def generated_details(row):
    return json.loads(row['prediction']).get('vision', {}) if row.get('prediction') else {}


def effective_details(row):
    return {**generated_details(row), **json.loads(row.get('user_edits', '{}'))}


def edit_revision(row):
    snapshot = [row.get(key) for key in ('path', 'mtime', 'bytes', 'prediction', 'user_edits')]
    return hashlib.sha256(json.dumps(snapshot).encode('utf-8')).hexdigest()


def validate_details(values):
    if not isinstance(values, dict) or set(values) != set(DEFAULTS):
        raise ValueError('Submit the description, tags, medium, mood, composition, and detection flags.')
    clean = {}
    for key, default in DEFAULTS.items():
        value = values[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError('Detection flags must be on or off.')
        elif isinstance(default, list):
            if not isinstance(value, list) or len(value) > 100:
                raise ValueError(f'Use at most 100 entries for {key}.')
            unique, seen = [], set()
            for entry in value:
                if not isinstance(entry, str) or len(entry) > 120:
                    raise ValueError(f'Each {key} entry must be text, at most 120 characters.')
                entry = entry.strip()
                if entry and entry.casefold() not in seen:
                    unique.append(entry)
                    seen.add(entry.casefold())
            value = unique
        else:
            limit = 8000 if key == 'caption' else 120
            if not isinstance(value, str) or len(value) > limit:
                raise ValueError(f'{key.capitalize()} must be text, at most {limit} characters.')
            value = value.strip()
        clean[key] = value
    return clean
