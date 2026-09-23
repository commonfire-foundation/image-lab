from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from imagescope import AnalysisRequest, analyze

from image_lab_ui.analyzer_client import AnalyzerProcessError, inspect_measurements, validate_measurement_result
from image_lab_ui.measurement_services import measure_file, present_measurements
from image_lab_ui.records import legacy_record


class MeasurementServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'source.png'
        Image.new('RGB', (60, 40), 'red').save(self.path)

    def test_public_measurements_are_reused_exactly_without_model_or_source_changes(self):
        reference = analyze(AnalysisRequest(source=self.path, task='inspect'))
        original = self.path.read_bytes()
        before = self.path.stat()
        with patch('imagescope.analyze', wraps=analyze) as provider:
            view = measure_file(self.path, (before.st_mtime_ns, before.st_size))
        self.assertEqual(view['error'], '')
        request = provider.call_args.args[0]
        self.assertEqual((request.task, request.color_policy, request.palette_size, request.assume_srgb),
                         ('inspect', 'legacy-v1', 6, False))
        self.assertEqual(view['palette'], reference['measurements']['palette'])
        self.assertEqual(view['result']['measurements'], reference['measurements'])
        self.assertFalse(view['colorAgreement'])
        self.assertIn('unverified', view['notice'])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_policy_versions_source_and_sampling_are_required(self):
        reference = inspect_measurements(self.path)
        for field in ('policy', 'version', 'source', 'sampling', 'settings'):
            result = deepcopy(reference)
            if field == 'policy':
                result['provenance']['preprocessing']['color_management']['policy'] = 'srgb-v1'
            elif field == 'version':
                result['provenance']['measurements_version'] = 99
            elif field == 'source':
                result['input']['path'] += '.old'
            elif field == 'sampling':
                del result['provenance']['preprocessing']['working_width']
            else:
                result['provenance']['measurement_settings']['palette_size'] = 12
            with self.subTest(field=field), self.assertRaises(AnalyzerProcessError):
                validate_measurement_result(result, self.path)
        reference['future_addition'] = True
        validate_measurement_result(reference, self.path)

    def test_visible_provenance_and_original_coordinates_are_not_invented(self):
        Image.new('RGB', (2400, 1200), 'blue').save(self.path)
        view = measure_file(self.path)
        self.assertEqual(view['error'], '')
        rows = {r['label']: r['value'] for g in view['groups'] for r in g['rows']}
        self.assertEqual(rows['Color policy'], 'legacy-v1')
        self.assertEqual(rows['Color interpretation'], 'unmanaged')
        self.assertEqual(rows['Output color space'], 'Unknown')
        self.assertEqual(rows['Working raster'], '2048 × 1024 px')
        self.assertEqual(rows['Downsampled'], 'Yes')
        self.assertIn('256 × 256', rows['Palette / distribution sampling'])
        self.assertIn('never exact', rows['Bounds limitation'])
        self.assertIn('first frame', rows['Scope'])

    def test_transparency_is_not_replaced_with_black_or_zero_unknowns(self):
        Image.new('RGBA', (60, 40), (255, 0, 0, 0)).save(self.path)
        view = measure_file(self.path)
        self.assertEqual(view['error'], '')
        self.assertEqual(view['palette'], [])
        rows = {r['label']: r['value'] for g in view['groups'] for r in g['rows']}
        self.assertEqual(rows['Median · opacity-weighted, no background'], 'Unknown')
        self.assertEqual(rows['Transparent share'], '100.00%')
        self.assertEqual(rows['Translucent share'], '0.00%')
        self.assertEqual(rows['Visible bounds · working pixels'], 'None · no visible pixels')

    def test_stale_catalog_and_mid_read_changes_are_rejected(self):
        with patch('image_lab_ui.measurement_services.inspect_measurements') as provider:
            view = measure_file(self.path, (0, 0))
            provider.assert_not_called()
        self.assertEqual(view['errorCode'], 'source_changed')
        reference = inspect_measurements(self.path)
        def changed(path):
            Image.new('RGB', (30, 20), 'blue').save(path)
            return reference
        with patch('image_lab_ui.measurement_services.inspect_measurements', side_effect=changed):
            view = measure_file(self.path)
        self.assertEqual(view['errorCode'], 'source_changed')
        self.assertEqual(view['groups'], [])

    def test_invalid_palette_and_missing_source_are_visible_failures(self):
        result = inspect_measurements(self.path)
        result['measurements']['palette'][0]['hex'] = 'not-a-color'
        with self.assertRaises(ValueError):
            present_measurements(result, self.path)
        with patch('image_lab_ui.measurement_services.inspect_measurements', side_effect=ImportError):
            self.assertEqual(measure_file(self.path)['errorCode'], 'measurement_provider_unavailable')
        self.path.unlink()
        self.assertEqual(measure_file(self.path)['errorCode'], 'source_unavailable')

    def test_analysis_storage_adapter_retains_measurement_provenance(self):
        result = inspect_measurements(self.path)
        record = legacy_record(result, self.path)
        self.assertEqual(record['analysis_provenance'], result['provenance'])
        self.assertEqual(record['analysis']['palette'], result['measurements']['palette'])
        self.assertEqual(record['analysis_schema_version'], 1)
        self.assertIsNone(record['vision'])


if __name__ == '__main__':
    unittest.main()
