import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_QUICK_BACKEND', 'software')
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtGui import QGuiApplication, QPalette
    from image_lab_ui.omarchy_palette import (DEFAULT_COLORS, OmarchyPalette,
                                              palette_from_toml, qt_palette, theme_paths)


def scheme(bg='#102030', fg='#e0e8f0', accent='#55bbcc'):
    return f'background = "{bg}"\nforeground = "{fg}"\naccent = "{accent}"\ncolor1 = "#dd4433"\n'


@unittest.skipUnless(HAS_QT, 'Install the desktop extra for Qt tests')
class OmarchyPaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = self.root / 'current'
        self.theme = self.current / 'theme'
        self.theme.mkdir(parents=True)
        self.path = self.theme / 'colors.toml'

    def palette(self, paths=None):
        result = OmarchyPalette(paths=[self.path] if paths is None else paths, interval_ms=25)
        self.addCleanup(lambda: result.timer.stop())
        return result

    def wait_for_color(self, palette, expected):
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        def changed():
            if palette.colors['background'] == expected:
                loop.quit()
        palette.changed.connect(changed)
        timeout.start(2000)
        loop.exec()
        palette.changed.disconnect(changed)
        self.assertEqual(palette.colors['background'], expected)

    def test_paths_follow_state_then_legacy_with_absolute_xdg_support(self):
        paths = theme_paths(self.root, {})
        self.assertEqual(paths, [self.root / '.local/state/omarchy/current/theme/colors.toml',
                                 self.root / '.config/omarchy/current/theme/colors.toml'])
        self.assertEqual(theme_paths(self.root, {'XDG_STATE_HOME': 'relative'}), paths)
        override = self.root / 'state'
        self.assertEqual(theme_paths(self.root, {'XDG_STATE_HOME': str(override)})[0],
                         override / 'omarchy/current/theme/colors.toml')

    def test_dark_and_light_palettes_use_semantic_colors(self):
        dark = palette_from_toml((scheme() + 'lighter_bg = "#203040"\nred = "#f06655"\n'
                                 'selection_background = "#334455"\nselection_foreground = "#ffffff"\n').encode())
        self.assertEqual(dark['panel'], '#203040')
        self.assertEqual(dark['error'], '#f06655')
        self.assertEqual(dark['selectionText'], '#ffffff')
        light = palette_from_toml(scheme('#fafafa', '#202020', '#225599').encode())
        self.assertEqual(light['background'], '#fafafa')
        self.assertGreater(int(light['panel'][1:3], 16), 200)
        self.assertLess(int(light['muted'][1:3], 16), 150)
        qt = qt_palette(light)
        self.assertEqual(qt.color(QPalette.ColorRole.Window).name(), '#fafafa')
        self.assertEqual(qt.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name(), light['disabled'])

    def test_missing_partial_and_oversized_files_keep_last_good_palette(self):
        palette = self.palette()
        self.assertEqual(palette.colors, DEFAULT_COLORS)
        self.path.write_text(scheme())
        self.wait_for_color(palette, '#102030')
        previous = dict(palette.colors)
        notifications = []
        palette.changed.connect(lambda: notifications.append(True))
        for data in (b'background = "unfinished', b'background="bad"\nforeground="#ffffff"',
                     b'\xff', b' ' * (64 * 1024 + 1)):
            self.path.write_bytes(data)
            palette.reload()
            self.assertEqual(palette.colors, previous)
        self.path.unlink()
        palette.reload()
        self.assertEqual(palette.colors, previous)
        self.path.write_text(scheme())
        palette.reload()
        self.assertEqual(notifications, [])

    def test_hot_reload_atomic_file_and_whole_directory_replacement(self):
        self.path.write_text(scheme())
        palette = self.palette()
        staged = self.theme / 'next.toml'
        staged.write_text(scheme('#221133'))
        staged.replace(self.path)
        self.wait_for_color(palette, '#221133')
        self.theme.rename(self.current / 'old-theme')
        palette.reload()
        self.assertEqual(palette.colors['background'], '#221133')
        self.theme.mkdir()
        self.path.write_text(scheme('#fafafa', '#202020'))
        self.wait_for_color(palette, '#fafafa')

    def test_hot_reload_symlink_and_state_precedence(self):
        first = self.root / 'first'
        second = self.root / 'second'
        first.mkdir(); second.mkdir()
        (first / 'colors.toml').write_text(scheme())
        (second / 'colors.toml').write_text(scheme('#334455'))
        link = self.root / 'legacy'
        link.symlink_to(first, target_is_directory=True)
        palette = self.palette([self.path, link / 'colors.toml'])
        self.assertEqual(palette.colors['background'], '#102030')
        replacement = self.root / 'next-link'
        replacement.symlink_to(second, target_is_directory=True)
        replacement.replace(link)
        self.wait_for_color(palette, '#334455')
        self.path.write_text(scheme('#112211'))
        self.wait_for_color(palette, '#112211')
        self.path.unlink()
        palette.reload()
        self.assertEqual(palette.colors['background'], '#112211')


if __name__ == '__main__':
    unittest.main()
