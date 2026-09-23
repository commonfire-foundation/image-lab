"""Read-only Omarchy palette integration, owned entirely by Image Lab."""
import os
from pathlib import Path
import re
import tomllib

from PySide6.QtCore import QObject, QTimer, Signal

# Used outside Omarchy, or until the first complete palette becomes available.
DEFAULT_COLORS = {
    'background': '#20242a', 'foreground': '#edf1f5', 'muted': '#a9b3c0',
    'accent': '#7fc5c5', 'panel': '#292e36', 'border': '#414a56',
    'button': '#353d47', 'disabled': '#78828d', 'preview': '#181c22',
    'selection': '#35434b', 'selectionText': '#d3e9e8', 'error': '#efaf98',
    'accentText': '#18272b',
}
MAX_PALETTE_BYTES = 64 * 1024


def theme_paths(home=None, environ=None):
    home = Path.home() if home is None else Path(home)
    env = os.environ if environ is None else environ
    def xdg(name, fallback):
        value = env.get(name, '')
        return Path(value) if value and Path(value).is_absolute() else fallback
    # Omarchy 4 stages a directory in state, removing/replacing it on switches.
    # Also recognize the older config symlink and absolute XDG overrides.
    roots = [xdg('XDG_STATE_HOME', home / '.local/state'), home / '.local/state',
             xdg('XDG_CONFIG_HOME', home / '.config'), home / '.config']
    return list(dict.fromkeys(root / 'omarchy/current/theme/colors.toml' for root in roots))


def mix(background, foreground, amount):
    a = [int(background[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(foreground[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(x + (y - x) * amount):02x}' for x, y in zip(a, b))


def palette_from_toml(data):
    values = tomllib.loads(data.decode('utf-8'))
    def color(*keys, default=None):
        for key in keys:
            if key in values:
                value = values[key]
                if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                    raise ValueError(f'Invalid palette color: {key}')
                return value.lower()
        if default is None:
            raise ValueError(f'Missing palette color: {keys[0]}')
        return default
    bg = color('background', 'bg')
    fg = color('foreground', 'fg')
    accent = color('accent', 'color4', default=fg)
    panel = color('lighter_bg', default=mix(bg, fg, 0.06))
    return {
        'background': bg, 'foreground': fg, 'accent': accent,
        'panel': panel, 'button': mix(bg, fg, 0.12),
        'border': mix(bg, fg, 0.28),
        'muted': color('muted', default=mix(bg, fg, 0.65)),
        'disabled': mix(bg, fg, 0.45),
        'preview': color('dark_bg', 'darker_bg', default=bg),
        'selection': color('selection_background', 'selection', default=mix(bg, accent, 0.25)),
        'selectionText': color('selection_foreground', default=fg),
        'error': color('red', 'color1', default=accent),
        'accentText': bg,
    }


def qt_palette(colors):
    """Also theme Qt-created controls/windows such as the folder chooser."""
    from PySide6.QtGui import QColor, QPalette
    palette = QPalette()
    roles = {
        'Window': 'background', 'WindowText': 'foreground', 'Base': 'background',
        'AlternateBase': 'panel', 'ToolTipBase': 'panel', 'ToolTipText': 'foreground',
        'Text': 'foreground', 'Button': 'button', 'ButtonText': 'foreground',
        'BrightText': 'error', 'Highlight': 'selection', 'HighlightedText': 'selectionText',
        'PlaceholderText': 'muted', 'Link': 'accent', 'LinkVisited': 'accent',
        'Light': 'button', 'Midlight': 'panel', 'Mid': 'border', 'Dark': 'preview', 'Shadow': 'preview',
    }
    for role, token in roles.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(colors[token]))
    for role in ('ButtonText', 'Text', 'WindowText'):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role), QColor(colors['disabled']))
    return palette


class OmarchyPalette(QObject):
    changed = Signal()

    def __init__(self, parent=None, paths=None, interval_ms=500):
        super().__init__(parent)
        self.paths = theme_paths() if paths is None else [Path(p) for p in paths]
        self.colors = dict(DEFAULT_COLORS)
        self._active_path = None
        self._last_data = None
        self.reload()
        # Reopen the logical path rather than watching an inode that Omarchy
        # removes on every switch. This also follows replaced legacy symlinks.
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.reload)
        self.timer.start()

    def reload(self):
        for path in self.paths:
            try:
                if not path.is_file():
                    raise FileNotFoundError(path)
                with path.open('rb') as source:
                    data = source.read(MAX_PALETTE_BYTES + 1)
            except OSError:
                # A switch has a brief missing-directory window. Keep the last
                # palette instead of flashing a fallback/obsolete legacy theme.
                if path == self._active_path:
                    return
                continue
            if len(data) > MAX_PALETTE_BYTES:
                return
            if (path, data) == self._last_data:
                return
            try:
                colors = palette_from_toml(data)
            except (ValueError, UnicodeError):
                return  # Partial/malformed writes must not repaint the UI.
            self._active_path = path
            self._last_data = (path, data)
            if colors != self.colors:
                self.colors = colors
                self.changed.emit()
            return
