from contextlib import contextmanager
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zlib

from PIL import Image, ImageCms, PngImagePlugin
from image_lab_ui.edit_color import render_color_geometry
from test_edit_color import linear_rgb_profile
from imagescope import AnalysisRequest, analyze
import io

from image_lab_ui.edit_process import prepare_source, render_source
from image_lab_ui.edit_protocol import EditWorkerError, MAX_INPUT_BYTES, SourceSnapshot
from image_lab_ui.edit_recipe import Crop, EditRecipe, Size
from image_lab_ui.edit_worker import _check_current

ROOT = Path(__file__).resolve().parents[1]
FAULT = ROOT / 'tests' / 'helpers' / 'edit_worker_fault.py'


@unittest.skipUnless(sys.platform.startswith('linux'), 'Worker isolation is Linux-only')
class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'source.png'
        Image.new('RGB', (20, 10), 'red').save(self.path)
        self.recipe = EditRecipe.original(20, 10)

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(EditWorkerError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code, str(caught.exception))

    @contextmanager
    def fault(self, mode):
        processes = []
        popen = subprocess.Popen

        def launch(command, **kwargs):
            process = popen([sys.executable, str(FAULT), mode], **kwargs)
            processes.append(process)
            return process

        with patch('image_lab_ui.edit_process.subprocess.Popen', side_effect=launch):
            yield processes
        for process in processes:
            self.assertIsNotNone(process.poll(), 'Worker was not reaped')
            self.assertTrue(process.stdin.closed)
            self.assertTrue(process.stdout.closed)
            self.assertTrue(process.stderr.closed)

    def test_snapshot_full_decode_and_full_resolution_render_preserve_original(self):
        before, stamp = self.path.read_bytes(), self.path.stat().st_mtime_ns
        snapshot = prepare_source(self.path)
        self.assertEqual(snapshot.sha256, hashlib.sha256(before).hexdigest())
        self.assertEqual(snapshot.stored_size, Size(20, 10))
        self.assertTrue(snapshot.orientation_assumed)
        self.assertEqual(SourceSnapshot.from_dict(snapshot.to_dict()), snapshot)
        full = render_source(snapshot, self.recipe.rotated(), preview_longest=None,
                             request_id='session-one', generation=7)
        self.assertEqual(full.request_id, 'session-one')
        self.assertEqual(full.generation, 7)
        self.assertEqual(full.size, Size(10, 20))
        self.assertEqual(full.full_resolution_pixels(), bytes((255, 0, 0)) * 200)
        self.assertEqual(full.color_interpretation, 'unmanaged')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, stamp)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_preview_and_intended_output_remain_distinct(self):
        snapshot = prepare_source(self.path)
        preview = render_source(snapshot, self.recipe, preview_longest=8)
        self.assertEqual(preview.size, Size(8, 4))
        self.assertEqual(preview.output_size, Size(20, 10))
        self.assert_code('preview_not_exportable', preview.full_resolution_pixels)
        small = render_source(snapshot, self.recipe, preview_longest=2048)
        self.assertEqual(small.size, small.output_size)
        self.assert_code('preview_not_exportable', small.full_resolution_pixels)

    def test_full_render_uses_original_pixels_beyond_analysis_preview_limit(self):
        Image.new('RGB', (2600, 4), 'blue').save(self.path)
        snapshot = prepare_source(self.path)
        recipe = EditRecipe.original(2600, 4)
        preview = render_source(snapshot, recipe)
        full = render_source(snapshot, recipe, preview_longest=None)
        self.assertEqual(preview.size.width, 2048)
        self.assertEqual(full.size, Size(2600, 4))
        self.assertEqual(full.full_resolution_pixels(), bytes((0, 0, 255)) * 2600 * 4)

    def test_alpha_and_icc_identity_without_conversion_claim(self):
        Image.new('RGBA', (20, 10), (1, 2, 3, 50)).save(self.path, icc_profile=b'test-profile')
        snapshot = prepare_source(self.path)
        self.assertEqual(snapshot.icc_sha256, hashlib.sha256(b'test-profile').hexdigest())
        result = render_source(snapshot, self.recipe, preview_longest=None)
        self.assertEqual(result.mode, 'RGBA')
        self.assertEqual(result.pixels, bytes((1, 2, 3, 50)) * 200)
        self.assertEqual(result.color_conversion, 'none')
        self.assertEqual(result.icc_profile, b'test-profile')
        self.assertEqual(result.color.status, 'unmanaged')

    def test_managed_worker_matches_core_and_public_measurements_all_orientations(self):
        raw = linear_rgb_profile()
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                with Image.frombytes('RGBA', (3, 2), bytes((32, 64, 128, 0, 100, 40, 60, 64,
                        128, 128, 128, 128, 32, 32, 32, 255, 64, 64, 64, 255, 192, 192, 192, 255))) as source:
                    exif = Image.Exif(); exif[274] = orientation
                    source.save(self.path, icc_profile=raw, exif=exif)
                original = self.path.read_bytes()
                stamp = self.path.stat().st_mtime_ns
                snapshot = prepare_source(self.path)
                recipe = EditRecipe.original(snapshot.oriented_size.width, snapshot.oriented_size.height)
                for preview in (None, 2):
                    result = render_source(snapshot, recipe, preview_longest=preview,
                        color_policy='srgb-v1', generation=orientation, request_id='managed-fixture')
                    with Image.open(self.path) as loaded:
                        loaded.load()
                        with loaded.copy() as pixels:
                            expected = render_color_geometry(pixels, recipe, orientation=orientation,
                                policy='srgb-v1', preview_longest=preview)
                    try:
                        self.assertEqual(result.pixels, expected.image.tobytes())
                        self.assertEqual(result.color, expected.color)
                    finally:
                        expected.image.close()
                    self.assertEqual(result.color_interpretation, 'srgb')
                    self.assertEqual(result.color_conversion, 'converted')
                    self.assertNotEqual(result.icc_profile, raw)
                    self.assertEqual(result.generation, orientation)
                    if preview is not None:
                        self.assert_code('preview_not_exportable', result.full_resolution_pixels)
                    else:
                        with Image.frombytes(result.mode, (result.size.width, result.size.height), result.full_resolution_pixels()) as output:
                            data = io.BytesIO(); output.save(data, 'PNG', icc_profile=result.icc_profile)
                        reference = analyze(AnalysisRequest(original, task='inspect', color_policy='srgb-v1'))
                        actual = analyze(AnalysisRequest(data.getvalue(), task='inspect', color_policy='srgb-v1'))
                        self.assertEqual(reference['status'], 'ok')
                        self.assertEqual(actual['status'], 'ok')
                        self.assertEqual(actual['measurements'], reference['measurements'])
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.path.stat().st_mtime_ns, stamp)

    def test_managed_unknown_declared_assumed_and_broken_profiles(self):
        snapshot = prepare_source(self.path)
        self.assert_code('unknown_color_space', render_source, snapshot, self.recipe, color_policy='srgb-v1')
        result = render_source(snapshot, self.recipe, color_policy='srgb-v1', assume_srgb=True)
        self.assertEqual(result.color.status, 'assumed_srgb')
        self.assertIsNone(result.icc_profile)
        self.assertEqual(result.color_conversion, 'none')
        self.assertEqual(result.color_interpretation, 'srgb')
        with self.fault('false_declaration'):
            self.assert_code('protocol_error', render_source, snapshot, self.recipe,
                             color_policy='srgb-v1', assume_srgb=True)
        pnginfo = PngImagePlugin.PngInfo(); pnginfo.add(b'sRGB', b'\x00')
        with Image.new('RGB', (20, 10), 'red') as source:
            source.save(self.path, pnginfo=pnginfo)
            snapshot = prepare_source(self.path)
            result = render_source(snapshot, self.recipe, color_policy='srgb-v1')
            self.assertEqual(snapshot.srgb_intent, 0)
            self.assertEqual(result.color.status, 'declared_srgb')
            self.assertIsNone(result.icc_profile)
            source.save(self.path, pnginfo=pnginfo, icc_profile=b'broken-profile')
        snapshot = prepare_source(self.path)
        self.assert_code('invalid_color_profile', render_source, snapshot, self.recipe,
                         color_policy='srgb-v1', assume_srgb=True)

    def test_legacy_profile_larger_than_json_header_is_transported_opaquely(self):
        raw = bytes(range(256)) * 300
        with Image.new('RGB', (20, 10), 'red') as image:
            image.save(self.path, icc_profile=raw)
        snapshot = prepare_source(self.path)
        result = render_source(snapshot, self.recipe, preview_longest=None)
        self.assertEqual(result.icc_profile, raw)
        self.assertEqual(result.full_resolution_pixels(), bytes((255, 0, 0)) * 200)
        self.assertEqual(result.color.source_profile_sha256, hashlib.sha256(raw).hexdigest())

    def test_managed_profile_source_change_is_rejected(self):
        with Image.new('RGB', (20, 10), 'red') as image:
            image.save(self.path, icc_profile=linear_rgb_profile())
            snapshot = prepare_source(self.path)
            image.save(self.path, icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        self.assert_code('source_changed', render_source, snapshot, self.recipe, color_policy='srgb-v1')

    def test_managed_full_resolution_is_not_analysis_raster(self):
        with Image.new('RGB', (2600, 4), (128, 128, 128)) as image:
            image.save(self.path, icc_profile=linear_rgb_profile())
        snapshot = prepare_source(self.path)
        recipe = EditRecipe.original(2600, 4)
        result = render_source(snapshot, recipe, color_policy='srgb-v1', preview_longest=None)
        self.assertEqual(result.size, Size(2600, 4))
        self.assertEqual(len(result.full_resolution_pixels()), 2600 * 4 * 3)
        self.assertTrue(all(abs(value - 188) <= 1 for value in result.pixels[:3]))

    def test_managed_transport_rejects_forged_provenance_and_profile_payloads(self):
        with Image.new('RGB', (20, 10), 'red') as image:
            image.save(self.path, icc_profile=linear_rgb_profile())
        snapshot = prepare_source(self.path)
        for mode in ('old_version', 'wrong_policy', 'wrong_assumption', 'wrong_icc_identity',
                     'wrong_intent', 'wrong_order', 'bpc', 'optimization', 'missing_color',
                     'profile_hash', 'profile_large', 'profile_missing', 'profile_header',
                     'profile_truncated', 'stale', 'wrong_id', 'extra'):
            with self.subTest(mode=mode), self.fault(mode):
                self.assert_code('protocol_error', render_source, snapshot, self.recipe, color_policy='srgb-v1')

    def test_managed_cancel_and_deadline_reap_children(self):
        snapshot = prepare_source(self.path)
        with self.fault('hang'):
            self.assert_code('timeout', render_source, snapshot, self.recipe,
                color_policy='srgb-v1', assume_srgb=True, timeout=0.2)
        with self.fault('hang'):
            start = time.monotonic()
            self.assert_code('cancelled', render_source, snapshot, self.recipe,
                color_policy='srgb-v1', assume_srgb=True, cancelled=lambda: time.monotonic() - start > 0.15)

    def test_color_options_rejected_before_spawn(self):
        snapshot = prepare_source(self.path)
        with patch('image_lab_ui.edit_process.subprocess.Popen') as spawn:
            for policy, assumption in (('other', False), ('legacy-v1', True), ('srgb-v1', 1), (None, False)):
                with self.subTest(policy=policy, assumption=assumption), self.assertRaises(ValueError):
                    render_source(snapshot, self.recipe, color_policy=policy, assume_srgb=assumption)
            spawn.assert_not_called()

    def test_all_orientations_are_normalized_once_before_crop(self):
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                image = Image.new('RGB', (3, 2))
                image.putdata([(n, 0, 0) for n in range(1, 7)])
                exif = Image.Exif()
                exif[274] = orientation
                image.save(self.path, exif=exif)
                snapshot = prepare_source(self.path)
                self.assertEqual(snapshot.orientation, orientation)
                self.assertFalse(snapshot.orientation_assumed)
                size = snapshot.oriented_size
                recipe = EditRecipe.original(size.width, size.height).with_crop(Crop(0, 0, 1, 1))
                result = render_source(snapshot, recipe, preview_longest=None)
                expected_corner = {1: 1, 2: 3, 3: 6, 4: 4, 5: 1, 6: 4, 7: 6, 8: 3}[orientation]
                self.assertEqual(result.pixels, bytes((expected_corner, 0, 0)))

    def test_reject_modified_replaced_missing_and_wrong_digest_sources(self):
        snapshot = prepare_source(self.path)
        self.assert_code('source_changed', render_source,
                         replace(snapshot, sha256='0' * 64), self.recipe)
        replacement = self.root / 'replacement.png'
        Image.new('RGB', (20, 10), 'blue').save(replacement)
        os.replace(replacement, self.path)
        self.assert_code('source_changed', render_source, snapshot, self.recipe)
        self.assert_code('source_changed', _check_current, snapshot)
        snapshot = prepare_source(self.path)
        Image.new('RGB', (20, 10), 'green').save(self.path)
        self.assert_code('source_changed', render_source, snapshot, self.recipe)
        self.path.unlink()
        self.assert_code('source_changed', render_source, snapshot, self.recipe)
        self.assert_code('source_unavailable', prepare_source, self.path)

    def test_reject_symlink_fifo_and_oversized_encoded_source(self):
        link = self.root / 'link.png'
        link.symlink_to(self.path)
        self.assert_code('unsupported_source', prepare_source, link)
        fifo = self.root / 'pipe.png'
        os.mkfifo(fifo)
        self.assert_code('unsupported_source', prepare_source, fifo, timeout=2)
        big = self.root / 'too-big.png'
        with big.open('wb') as stream:
            stream.truncate(MAX_INPUT_BYTES + 1)
        self.assert_code('input_limit', prepare_source, big)

    def test_corrupt_pixels_and_unsupported_modes_sequences(self):
        self.path.write_bytes(b'not an image')
        self.assert_code('decode_failed', prepare_source, self.path)
        for mode, filename in [('I;16', 'deep.png'), ('L', 'gray.png'), ('P', 'indexed.png'),
                               ('RGB', 'single.gif'), ('RGB', 'single.tiff')]:
            with self.subTest(mode=mode, filename=filename):
                path = self.root / filename
                Image.new(mode, (20, 10)).save(path)
                self.assert_code('unsupported_source', prepare_source, path)
        frames = [Image.new('RGB', (20, 10), color) for color in ('red', 'blue')]
        frames[0].save(self.path, save_all=True, append_images=frames[1:], duration=80)
        self.assert_code('unsupported_source', prepare_source, self.path)

    def test_color_key_transparency_is_not_silently_flattened(self):
        Image.new('RGB', (20, 10), 'red').save(self.path, transparency=(255, 0, 0))
        self.assert_code('unsupported_source', prepare_source, self.path)

    def test_pixel_budget_before_raster_allocation(self):
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        # Valid PNG header whose raster must never be allocated.
        self.path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 40001, 1000, 8, 2, 0, 0, 0))
                              + chunk(b'IDAT', b'') + chunk(b'IEND', b''))
        self.assert_code('input_limit', prepare_source, self.path)

    def test_deadline_kills_and_reaps_stalled_worker(self):
        snapshot = prepare_source(self.path)
        with self.fault('hang'):
            start = time.monotonic()
            self.assert_code('timeout', render_source, snapshot, self.recipe, timeout=0.2)
            self.assertLess(time.monotonic() - start, 2)

    def test_cancel_kills_and_reaps_worker_and_pre_cancel_does_not_spawn(self):
        with patch('image_lab_ui.edit_process.subprocess.Popen') as spawn:
            self.assert_code('cancelled', prepare_source, self.path, cancelled=lambda: True)
            spawn.assert_not_called()
        snapshot = prepare_source(self.path)
        with self.fault('hang'):
            start = time.monotonic()
            self.assert_code('cancelled', render_source, snapshot, self.recipe,
                             cancelled=lambda: time.monotonic() - start > 0.15)
            self.assertLess(time.monotonic() - start, 2)

    def test_crashes_cpu_memory_and_output_limits(self):
        snapshot = prepare_source(self.path)
        for mode, code in [('crash', 'worker_failed'), ('signal', 'resource_limit'),
                           ('cpu', 'resource_limit'), ('memory', 'resource_limit'),
                           ('header_flood', 'output_limit'), ('stderr_flood', 'output_limit')]:
            with self.subTest(mode=mode), self.fault(mode):
                self.assert_code(code, render_source, snapshot, self.recipe, timeout=5)

    def test_protocol_rejects_stale_oversized_incomplete_and_false_color_results(self):
        snapshot = prepare_source(self.path)
        for mode in ('stale', 'wrong_id', 'wrong_dimensions', 'preview_mismatch',
                     'color_claim', 'oversized', 'duplicate', 'truncated', 'extra'):
            with self.subTest(mode=mode), self.fault(mode):
                self.assert_code('protocol_error', render_source, snapshot, self.recipe)

    def test_bad_public_arguments_rejected_before_spawn(self):
        snapshot = prepare_source(self.path)
        with patch('image_lab_ui.edit_process.subprocess.Popen') as spawn:
            for timeout in (True, 0, -1, float('nan'), float('inf'), 61, 10 ** 1000):
                with self.assertRaises(ValueError):
                    prepare_source(self.path, timeout=timeout)
            with self.assertRaises(ValueError):
                render_source(snapshot, EditRecipe.original(10, 20))
            with self.assertRaises(ValueError):
                render_source(snapshot, self.recipe, generation=True)
            with self.assertRaises(ValueError):
                render_source(snapshot, self.recipe, preview_longest=2049)
            spawn.assert_not_called()

    def test_spawn_failure_is_structured(self):
        with patch('image_lab_ui.edit_process.subprocess.Popen', side_effect=OSError('unavailable')):
            self.assert_code('worker_unavailable', prepare_source, self.path)

    def test_parent_lifetime_guard_is_installed(self):
        # Inspect the actual sandbox in a disposable child, without changing this process.
        code = '''import ctypes, os
from image_lab_ui.edit_worker import _sandbox
_sandbox(os.getppid(), 2)
value = ctypes.c_int()
assert ctypes.CDLL(None).prctl(2, ctypes.byref(value), 0, 0, 0) == 0
print(value.value)
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '9')


if __name__ == '__main__':
    unittest.main()
