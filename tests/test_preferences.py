import sqlite3
import tempfile
from pathlib import Path
import unittest

from image_lab_ui.catalog import Catalog
from image_lab_ui.preferences import DEFAULTS, load_preferences, save_preferences


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.catalog = Catalog(self.path)
        self.addCleanup(self.catalog.close)

    def test_defaults_and_persistence(self):
        self.assertEqual(load_preferences(self.catalog.db), DEFAULTS)
        values = dict.fromkeys(DEFAULTS, False)
        save_preferences(self.catalog.db, values)
        reopened = Catalog(self.path)
        try:
            self.assertEqual(load_preferences(reopened.db), values)
        finally:
            reopened.close()

    def test_invalid_values_and_failed_write_do_not_replace_settings(self):
        save_preferences(self.catalog.db, DEFAULTS)
        for values in ({}, dict(DEFAULTS, autoplayViewerGifs='false'), dict(DEFAULTS, unknown=True)):
            with self.assertRaises(ValueError):
                save_preferences(self.catalog.db, values)
        self.catalog.db.execute("CREATE TRIGGER reject_preferences BEFORE INSERT ON preferences BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            save_preferences(self.catalog.db, dict.fromkeys(DEFAULTS, False))
        self.assertEqual(load_preferences(self.catalog.db), DEFAULTS)

    def test_malformed_saved_settings_fall_back_safely(self):
        for saved, expected in [('not json', DEFAULTS), ('[]', DEFAULTS),
                                ('{"autoplayViewerGifs":false,"autoplaySidebarGifs":"false"}', dict(DEFAULTS, autoplayViewerGifs=False))]:
            with self.catalog.db:
                self.catalog.db.execute("INSERT OR REPLACE INTO preferences VALUES ('playback',?)", (saved,))
            self.assertEqual(load_preferences(self.catalog.db), expected)


if __name__ == '__main__':
    unittest.main()
