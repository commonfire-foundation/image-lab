"""Small, deterministic filename suggestions from saved image metadata only."""
from pathlib import Path
import re
import unicodedata


_STOP_WORDS = frozenset('a an the and or of in on at to for with is are this that image photo picture showing shows features featuring'.split())
_RESERVED = frozenset(['con', 'prn', 'aux', 'nul', *[f'com{i}' for i in range(1, 10)], *[f'lpt{i}' for i in range(1, 10)]])


def _words(value):
    if not isinstance(value, str):
        return []
    text = unicodedata.normalize('NFKC', value).casefold()
    return [word for word in re.findall(r'[^\W_]+', text) if word not in _STOP_WORDS]


def suggest_names(image):
    """Return up to five distinct options; never invent missing metadata or touch disk."""
    if not image.get('analyzed'):
        return []
    caption = _words(image.get('caption'))
    tags = image.get('tags', [])
    tags = tags if isinstance(tags, list) else []
    subjects = [_words(tag) for tag in tags if isinstance(tag, str)]
    subjects = [words for words in subjects if words]
    tagged = [word for words in subjects for word in words]
    subject = subjects[0] if subjects else caption[:3]
    mood = _words(image.get('mood'))
    medium = _words(image.get('medium'))
    extension = Path(image.get('name', '')).suffix
    # Metadata without a subject is not enough to name the image meaningfully.
    if not caption and not tagged:
        return []
    candidates = [
        ('Descriptive', caption[:6] or tagged[:6]),
        ('Tag-focused', tagged[:6]),
        ('Mood-led', mood[:2] + subject if mood else []),
        ('Medium-led', subject + medium[:2] if medium else []),
        ('Short', subject[:3]),
        ('Detailed', tagged[:3] + caption[:5]),
    ]
    result, seen = [], set()
    for style, words in candidates:
        stem = '-'.join(dict.fromkeys(words))
        # Bound by UTF-8 bytes too, leaving room for the original extension.
        stem = stem.encode('utf-8')[:100].decode('utf-8', errors='ignore').rstrip('-')
        if not stem:
            continue
        if stem in _RESERVED:
            stem = 'image-' + stem
        name = stem + extension
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        result.append({'style': style, 'name': name})
        if len(result) == 5:
            break
    return result
