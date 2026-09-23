"""Consumer-owned checks against the separately installed Imagescope backend."""
import hashlib
import importlib.metadata
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image
import imagescope
from imagescope import AnalysisRequest, analyze
from imagescope.contracts import validate_result
from image_lab_ui.analyzer_client import DEFAULT_COMMAND, analyzer_identity
from image_lab_ui.catalog import Catalog
from image_lab_ui.records import legacy_record


class ImagescopeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_separate_distribution_and_default_command(self):
        self.assertEqual(importlib.metadata.version('imagescope'), '0.1.0')
        self.assertEqual(DEFAULT_COMMAND, (sys.executable, '-m', 'imagescope'))
        checkout = Path(__file__).resolve().parents[1]
        self.assertFalse((checkout / 'image_analyzer').exists())
        self.assertNotEqual(Path(imagescope.__file__).resolve().parent, checkout / 'imagescope')
        self.assertTrue(analyzer_identity()['prompt_version'])

    def test_legacy_adapter_uses_predictions_not_diagnostics(self):
        prediction = {'caption': 'Red', 'subjects': [], 'medium': 'abstract',
                      'mood': [], 'lighting': [], 'composition': [], 'tags': ['red'],
                      'text_present': False, 'watermark_present': False}
        class Backend:
            def check_model(self, model):
                return {'name': model, 'digest': 'test'}, {'version': 'test'}
            def describe(self, image, model, preview_size, *, profile):
                if profile != 'wallpaper':
                    raise AssertionError(f'Unexpected profile: {profile}')
                return dict(prediction), {}
        path = self.root / 'red.png'
        Image.new('RGB', (120, 60), 'red').save(path)
        result = analyze(AnalysisRequest(path), backend=Backend())
        validate_result(result)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual(result['provenance']['profile'], 'wallpaper')
        result['diagnostics']['vision'] = {'caption': 'unvalidated replacement'}
        self.assertEqual(legacy_record(result, path)['vision'], prediction)

    def test_large_png_catalog_and_analyzer_agree(self):
        path = self.root / 'large.png'
        with Image.new('RGBA', (6000, 5000), (255, 0, 0, 128)) as original:
            original.save(path)
        original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        result = analyze(AnalysisRequest(path, task='inspect'))
        validate_result(result)
        self.assertEqual(result['status'], 'ok', result.get('error'))
        self.assertEqual((result['input']['width'], result['input']['height']), (6000, 5000))
        catalog = Catalog(self.root / 'catalog')
        try:
            catalog.import_image(path)
            row = catalog.rows()[0]
            self.assertEqual((row['width'], row['height']), (6000, 5000))
            with Image.open(row['thumbnail']) as thumb:
                self.assertLessEqual(max(thumb.size), 512)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original_hash)
        finally:
            catalog.close()
