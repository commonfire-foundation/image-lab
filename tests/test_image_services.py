from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from PIL import Image, ImageCms, TiffImagePlugin
from imagescope import MetadataRequest, inspect_metadata

from image_lab_ui.image_services import (MetadataContractError, inspect_file,
                                         present_metadata, validate_metadata_result)


class MetadataAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'source.png'
        Image.new('RGBA', (60, 40), (1, 2, 3, 100)).save(self.path)

    @staticmethod
    def facts(view):
        return {row['label']: row['value'] for group in view['groups'] for row in group['rows']}

    def test_public_api_cli_and_adapter_parity_unchanged_original(self):
        original, stamp = self.path.read_bytes(), self.path.stat().st_mtime_ns
        api = inspect_metadata(MetadataRequest(self.path))
        cli = subprocess.run([sys.executable, '-m', 'imagescope', 'metadata', str(self.path), '--json'],
                             capture_output=True, timeout=15)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['metadata'], api['metadata'])
        with patch('imagescope.contracts.validate_result', side_effect=AssertionError('analysis validator used')):
            view = inspect_file(self.path)
        self.assertEqual(view['error'], '')
        self.assertEqual(view['metadata'], api['metadata'])
        self.assertEqual(view['warnings'], api['warnings'])
        self.assertEqual(view['source']['sha256'], hashlib.sha256(original).hexdigest())
        facts = self.facts(view)
        self.assertEqual(facts['Stored dimensions'], '60 × 40 px')
        self.assertEqual(facts['Color mode'], 'RGBA')
        self.assertEqual(facts['Alpha / transparency declared'], 'Yes')
        self.assertEqual(facts['Aspect ratio'], '3:2')
        self.assertIn('None', facts['Pixel color conversion'])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.path.stat().st_mtime_ns, stamp)

    def test_oriented_jpeg_and_nested_exif_are_not_fabricated(self):
        path = self.root / 'camera.jpg'
        exif = Image.Exif()
        exif[271], exif[272], exif[274] = 'Camera maker', 'Model One', 6
        exif[34665] = {33434: TiffImagePlugin.IFDRational(1, 125), 42036: 'Lens One'}
        Image.new('RGB', (60, 40), 'blue').save(path, exif=exif)
        view = inspect_file(path)
        self.assertFalse(view['error'])
        facts = self.facts(view)
        self.assertEqual(facts['Stored dimensions'], '60 × 40 px')
        self.assertEqual(facts['Oriented dimensions'], '40 × 60 px')
        self.assertEqual(facts['Camera model'], 'Model One')
        self.assertNotIn('Lens', facts)
        self.assertNotIn('Exposure', facts)
        self.assertIn('unavailable', facts['Metadata scope'])
        self.assertIn('Unavailable', facts['Resolution (DPI)'])
        self.assertIn('34665', view['metadata']['exif']['tags'])

    def test_additional_formats_and_modes_are_reported_without_conversion(self):
        for name, mode in [('source.bmp', 'RGB'), ('source.webp', 'RGBA'), ('gray.png', 'L'),
                           ('palette.png', 'P'), ('cmyk.jpg', 'CMYK'), ('depth.tiff', 'I;16')]:
            with self.subTest(name=name):
                path = self.root / name
                Image.new(mode, (30, 20)).save(path)
                original = path.read_bytes()
                view = inspect_file(path)
                self.assertEqual(view['error'], '')
                self.assertEqual(view['metadata']['mode'], mode)
                self.assertEqual(view['metadata']['color_conversion'], 'none')
                self.assertEqual(path.read_bytes(), original)

    def test_all_orientation_dimensions_match_public_contract(self):
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                exif = Image.Exif()
                exif[274] = orientation
                Image.new('RGB', (60, 40)).save(self.path, exif=exif)
                view = inspect_file(self.path)
                self.assertEqual(view['error'], '')
                expected = '40 × 60 px' if orientation >= 5 else '60 × 40 px'
                self.assertEqual(self.facts(view)['Oriented dimensions'], expected)

    def test_unknown_gif_tiff_counts_and_png_exif_remain_unknown(self):
        frames = [Image.new('RGB', (20, 10), color) for color in ('red', 'blue')]
        for extension, label in [('gif', 'Frame count'), ('tiff', 'Page count')]:
            path = self.root / ('sequence.' + extension)
            frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
            view = inspect_file(path)
            self.assertEqual(view['error'], '')
            self.assertIsNone(view['metadata']['sequence']['count'])
            self.assertEqual(self.facts(view)[label], 'Unknown')
            self.assertTrue(any(item['field'] == 'sequence' for item in view['warnings']))
            if extension == 'gif':
                self.assertIsNone(view['metadata']['sequence']['animated'])
                self.assertEqual(self.facts(view)['Animated'], 'Unknown')
                self.assertEqual(self.facts(view)['Loop declaration'], '0')
                self.assertEqual(self.facts(view)['First frame duration'], '80 ms')
        view = inspect_file(self.path)
        self.assertEqual(self.facts(view)['EXIF status'], 'Unknown')
        self.assertIn('assume 1', self.facts(view)['EXIF orientation'])
        self.assertTrue(any(item['code'] == 'metadata_not_scanned' for item in view['warnings']))

    def test_icc_identification_is_not_conversion(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        Image.new('RGB', (60, 40)).save(self.path, icc_profile=profile)
        view = inspect_file(self.path)
        self.assertEqual(view['error'], '')
        self.assertEqual(view['metadata']['color_conversion'], 'none')
        self.assertEqual(view['metadata']['icc']['sha256'], hashlib.sha256(profile).hexdigest())
        self.assertEqual(self.facts(view)['ICC profile'], 'Embedded')
        self.assertIn('not converted', self.facts(view)['Interpretation'])
        Image.new('RGB', (60, 40)).save(self.path, icc_profile=b'broken-profile')
        view = inspect_file(self.path)
        self.assertEqual(view['error'], '')
        self.assertEqual(self.facts(view)['ICC profile'], 'Invalid profile')
        self.assertTrue(any(item['field'] == 'icc' for item in view['warnings']))
        oversized = self.root / 'oversized-profile.jpg'
        Image.new('RGB', (60, 40)).save(oversized, icc_profile=b'x' * (1024 * 1024 + 1))
        view = inspect_file(oversized)
        self.assertEqual(view['error'], '')
        self.assertEqual(self.facts(view)['ICC profile'], 'Parsing omitted')
        self.assertTrue(any(item['code'] == 'metadata_limit' for item in view['warnings']))

    def test_zero_false_and_unknown_are_distinct(self):
        result = inspect_metadata(MetadataRequest(self.path))
        result['metadata']['has_alpha_channel'] = None
        result['metadata']['sequence'].update(count=None, animated=None, loop=0, first_frame_duration_ms=0)
        result['metadata']['exif']['tags']['42036'] = None
        result['metadata']['icc'].update(status='unavailable', size_bytes=None)
        view = present_metadata(result, self.path)
        facts = self.facts(view)
        self.assertEqual(facts['Alpha / transparency declared'], 'Unknown')
        self.assertEqual(facts['Animated'], 'Unknown')
        self.assertEqual(facts['First frame duration'], '0 ms')
        self.assertEqual(facts['Loop declaration'], '0')
        self.assertEqual(facts['Lens'], 'Unknown')
        self.assertEqual(facts['ICC profile'], 'Parser unavailable')
        self.assertEqual(facts['Profile size'], 'Unknown')
        result['metadata']['sequence']['animated'] = False
        self.assertEqual(self.facts(present_metadata(result, self.path))['Animated'], 'No')

    def test_versions_missing_fields_and_false_conversion_are_rejected_without_fallback(self):
        good = inspect_metadata(MetadataRequest(self.path))
        for field, value in [('metadata_version', 2), ('metadata_version', True),
                             ('elapsed_seconds', float('nan'))]:
            bad = dict(good, **{field: value})
            with self.assertRaises(MetadataContractError):
                validate_metadata_result(bad)
        for mutation in ('conversion', 'missing', 'mismatched_size'):
            bad = deepcopy(good)
            if mutation == 'conversion':
                bad['metadata']['color_conversion'] = 'srgb'
            elif mutation == 'missing':
                del bad['metadata']['icc']
            else:
                bad['metadata']['oriented_size']['width'] = 1
            with self.assertRaises(MetadataContractError):
                validate_metadata_result(bad)
        with patch('imagescope.inspect_metadata', return_value=dict(good, metadata_version=2)):
            view = inspect_file(self.path)
        self.assertEqual(view['errorCode'], 'metadata_contract')
        self.assertEqual(view['groups'], [])
        good['future_additive_field'] = 'allowed'
        self.assertEqual(validate_metadata_result(good), good)

    def test_visible_provider_errors_missing_file_and_catalog_drift(self):
        self.assertEqual(inspect_file(self.root / 'missing.png')['errorCode'], 'source_unavailable')
        view = inspect_file(self.path, (0, 0))
        self.assertEqual(view['error'], '')
        self.assertTrue(any(item['code'] == 'catalog_source_changed' for item in view['warnings']))
        error = {'metadata_version': 1, 'status': 'error', 'metadata': None,
                 'input': {}, 'warnings': [], 'elapsed_seconds': 0,
                 'error': {'code': 'metadata_timeout', 'message': 'Inspection timed out'}}
        with patch('imagescope.inspect_metadata', return_value=error):
            view = inspect_file(self.path)
        self.assertEqual(view['errorCode'], 'metadata_timeout')
        self.assertEqual(view['error'], 'Inspection timed out')
        self.path.write_bytes(b'not an image')
        self.assertEqual(inspect_file(self.path)['errorCode'], 'invalid_input')

    def test_missing_public_api_is_reported_without_a_local_fallback(self):
        from types import ModuleType
        with patch.dict(sys.modules, {'imagescope': ModuleType('imagescope')}):
            view = inspect_file(self.path)
        self.assertEqual(view['errorCode'], 'provider_unavailable')
        self.assertEqual(view['groups'], [])

    def test_top_level_rational_is_unknown_not_fabricated(self):
        path = self.root / 'rational.jpg'
        exif = Image.Exif()
        exif[33434] = TiffImagePlugin.IFDRational(1, 125)
        Image.new('RGB', (60, 40)).save(path, exif=exif)
        view = inspect_file(path)
        self.assertEqual(view['error'], '')
        self.assertEqual(self.facts(view)['Exposure'], 'Unknown')
        self.assertTrue(any(item['code'] == 'metadata_omitted' for item in view['warnings']))

    def test_source_changes_during_read_are_rejected(self):
        result = inspect_metadata(MetadataRequest(self.path))
        def changed(request):
            Image.new('RGB', (80, 20)).save(self.path)
            return result
        with patch('imagescope.inspect_metadata', side_effect=changed):
            view = inspect_file(self.path)
        self.assertEqual(view['errorCode'], 'source_changed')
        self.assertEqual(view['groups'], [])

    def test_headers_without_valid_pixels_do_not_require_pixel_loading(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        self.path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 60, 40, 8, 2, 0, 0, 0))
                              + chunk(b'IDAT', b'not a valid compressed raster') + chunk(b'IEND', b''))
        view = inspect_file(self.path)
        self.assertEqual(view['error'], '')
        self.assertEqual(self.facts(view)['Stored dimensions'], '60 × 40 px')
        with self.assertRaises(OSError):
            with Image.open(self.path) as image:
                image.load()


if __name__ == '__main__':
    unittest.main()
