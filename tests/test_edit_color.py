from dataclasses import FrozenInstanceError
import hashlib
import io
import json
import struct
import unittest
from unittest.mock import patch

from PIL import Image, ImageCms, PngImagePlugin
from imagescope import AnalysisRequest, analyze

from image_lab_ui.edit_color import EditColorError, prepare_color_pixels, render_color_geometry
from image_lab_ui.edit_recipe import Crop, EditRecipe
from image_lab_ui.edit_render import render_geometry


def srgb_profile():
    return ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()


def linear_rgb_profile():
    """Synthetic sRGB primaries with gamma 1 TRCs; no vendor profile dependency.

    Uses the same ICC fixture construction described in Imagescope's color tests,
    generated locally rather than importing that repository's private test helpers.
    """
    raw = bytearray(srgb_profile())
    for index in range(int.from_bytes(raw[128:132], 'big')):
        entry = 132 + index * 12
        if raw[entry:entry + 4] in (b'rTRC', b'gTRC', b'bTRC'):
            offset = int.from_bytes(raw[entry + 4:entry + 8], 'big')
            raw[entry + 8:entry + 12] = (16).to_bytes(4, 'big')
            raw[offset:offset + 16] = b'para' + b'\0' * 8 + struct.pack('>i', 65536)
    return bytes(raw)


def encoded(image, **options):
    stream = io.BytesIO()
    image.save(stream, 'PNG', **options)
    return stream.getvalue()


class EditorColorTests(unittest.TestCase):
    def keep(self, image):
        self.addCleanup(image.close)
        return image

    def test_linear_ramp_matches_independent_srgb_transfer(self):
        image = self.keep(Image.frombytes('RGB', (256, 1), bytes(v for value in range(256) for v in (value,) * 3)))
        raw = linear_rgb_profile()
        image.info['icc_profile'] = raw
        before, info = image.tobytes(), dict(image.info)
        with patch('PIL.ImageCms.profileToProfile', wraps=ImageCms.profileToProfile) as transform:
            pixels, color = prepare_color_pixels(image, policy='srgb-v1')
        self.keep(pixels)
        self.assertEqual(int(transform.call_args.kwargs['flags']), 0x0100)
        self.assertEqual(transform.call_args.kwargs['renderingIntent'], ImageCms.Intent.RELATIVE_COLORIMETRIC)
        self.assertFalse(transform.call_args.kwargs['inPlace'])
        for value in range(256):
            linear = value / 255
            expected = round(255 * (12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055))
            for channel in pixels.getpixel((value, 0)):
                self.assertLessEqual(abs(channel - expected), 1)
        self.assertEqual(color.status, 'converted')
        self.assertEqual(color.source_interpretation, 'embedded_icc')
        self.assertEqual(color.source_profile_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(color.rendering_intent, 'relative-colorimetric')
        self.assertFalse(color.black_point_compensation)
        self.assertEqual(color.transform_optimization, 'disabled')
        self.assertTrue(color.littlecms_version)
        self.assertNotEqual(pixels.info['icc_profile'], raw)
        self.assertEqual(image.tobytes(), before)
        self.assertEqual(image.info, info)
        json.dumps(color.to_dict(), allow_nan=False)
        with self.assertRaises(FrozenInstanceError):
            color.status = 'assumed_srgb'

    def test_srgb_identity_and_alpha_are_preserved(self):
        image = self.keep(Image.frombytes('RGBA', (4, 1), bytes((32, 64, 128, 0, 100, 200, 50, 64, 255, 0, 0, 128, 30, 90, 60, 255))))
        image.info['icc_profile'] = srgb_profile()
        pixels, color = prepare_color_pixels(image, policy='srgb-v1')
        self.keep(pixels)
        self.assertEqual(pixels.tobytes(), image.tobytes())
        self.assertEqual(pixels.mode, 'RGBA')
        self.assertEqual(color.output_color_space, 'srgb')
        image.info['icc_profile'] = linear_rgb_profile()
        converted, _ = prepare_color_pixels(image, policy='srgb-v1')
        self.keep(converted)
        self.assertEqual(converted.getchannel('A').tobytes(), image.getchannel('A').tobytes())
        self.assertNotEqual(converted.convert('RGB').tobytes(), image.convert('RGB').tobytes())

    def test_legacy_is_explicit_unmanaged_and_does_not_parse_icc(self):
        image = self.keep(Image.new('RGB', (4, 2), (128, 64, 32)))
        image.info['icc_profile'] = b'broken-profile'
        with patch('image_lab_ui.edit_color._cms', side_effect=AssertionError('legacy parsed ICC')):
            pixels, color = prepare_color_pixels(image, policy='legacy-v1')
        self.keep(pixels)
        self.assertEqual(pixels.tobytes(), image.tobytes())
        self.assertEqual(pixels.info['icc_profile'], b'broken-profile')
        self.assertEqual(color.status, 'unmanaged')
        self.assertEqual(color.source_interpretation, 'unknown')
        self.assertIsNone(color.output_color_space)
        self.assertIsNone(color.order)

    def test_unknown_declared_and_assumed_are_not_conflated(self):
        image = self.keep(Image.new('RGB', (3, 2), 'red'))
        with self.assertRaises(EditColorError) as error:
            prepare_color_pixels(image, policy='srgb-v1')
        self.assertEqual(error.exception.code, 'unknown_color_space')
        with patch('image_lab_ui.edit_color._cms', side_effect=AssertionError('unnecessary CMS')):
            pixels, color = prepare_color_pixels(image, policy='srgb-v1', assume_srgb=True)
            self.keep(pixels)
            self.assertEqual(color.status, 'assumed_srgb')
            self.assertNotIn('icc_profile', pixels.info)
            reference = analyze(AnalysisRequest(encoded(image), task='inspect', color_policy='srgb-v1', assume_srgb=True))
            self.assertEqual(reference['status'], 'ok')
            self.assertEqual(color.status, reference['provenance']['preprocessing']['color_management']['status'])
            image.info['srgb'] = 0
            pixels, color = prepare_color_pixels(image, policy='srgb-v1')
            self.keep(pixels)
            self.assertEqual(color.status, 'declared_srgb')
            pnginfo = PngImagePlugin.PngInfo(); pnginfo.add(b'sRGB', b'\0')
            reference = analyze(AnalysisRequest(encoded(image, pnginfo=pnginfo), task='inspect', color_policy='srgb-v1'))
            self.assertEqual(reference['status'], 'ok')
            self.assertEqual(color.status, reference['provenance']['preprocessing']['color_management']['status'])
        image.info['srgb'] = True
        with self.assertRaises(EditColorError):
            prepare_color_pixels(image, policy='srgb-v1')

    def test_broken_and_oversized_profiles_override_any_assumption(self):
        image = self.keep(Image.new('RGB', (3, 2), 'red'))
        image.info['srgb'] = 0
        for raw, code in ((b'broken', 'invalid_color_profile'), (b'x' * (1024 * 1024 + 1), 'color_profile_too_large')):
            with self.subTest(code=code):
                image.info['icc_profile'] = raw
                with self.assertRaises(EditColorError) as error:
                    prepare_color_pixels(image, policy='srgb-v1', assume_srgb=True)
                self.assertEqual(error.exception.code, code)
        image.info['icc_profile'] = ImageCms.ImageCmsProfile(ImageCms.createProfile('LAB')).tobytes()
        with self.assertRaises(EditColorError) as error:
            prepare_color_pixels(image, policy='srgb-v1', assume_srgb=True)
        self.assertEqual(error.exception.code, 'unsupported_color_mode')

    def test_missing_cms_and_failed_transform_do_not_fall_back(self):
        image = self.keep(Image.new('RGB', (3, 2), 'red'))
        image.info['icc_profile'] = srgb_profile()
        with patch('image_lab_ui.edit_color.import_module', side_effect=ImportError):
            with self.assertRaises(EditColorError) as error:
                prepare_color_pixels(image, policy='srgb-v1', assume_srgb=True)
        self.assertEqual(error.exception.code, 'color_management_unavailable')
        with patch('PIL.ImageCms.profileToProfile', side_effect=ImageCms.PyCMSError('failure')):
            with self.assertRaises(EditColorError) as error:
                prepare_color_pixels(image, policy='srgb-v1', assume_srgb=True)
        self.assertEqual(error.exception.code, 'color_conversion_failed')

    def test_unsupported_modes_color_keys_lazy_pixels_and_parameters_rejected(self):
        for mode in ('CMYK', 'P', 'L', 'I;16'):
            image = self.keep(Image.new(mode, (3, 2)))
            with self.assertRaises(EditColorError) as error:
                prepare_color_pixels(image, policy='srgb-v1', assume_srgb=True)
            self.assertEqual(error.exception.code, 'unsupported_color_mode')
        image = self.keep(Image.new('RGB', (3, 2)))
        image.info['transparency'] = (0, 0, 0)
        with self.assertRaises(EditColorError):
            prepare_color_pixels(image, policy='srgb-v1', assume_srgb=True)
        image.info.clear()
        for policy, assumption in (('unknown', False), ('legacy-v1', True), ('srgb-v1', 1)):
            with self.assertRaises(EditColorError):
                prepare_color_pixels(image, policy=policy, assume_srgb=assumption)
        with self.assertRaises(TypeError):
            prepare_color_pixels(image)
        with Image.open(io.BytesIO(encoded(image))) as lazy:
            with self.assertRaises(EditColorError):
                prepare_color_pixels(lazy, policy='legacy-v1')

    def test_color_precedes_geometry_and_stale_source_metadata_is_removed(self):
        image = self.keep(Image.new('RGB', (10, 6), (128, 128, 128)))
        image.info.update(icc_profile=linear_rgb_profile(), exif=b'private source metadata')
        recipe = EditRecipe.original(6, 10).with_crop(Crop(1, 2, 5, 8)).rotated().resized_width(3)
        observed = []
        def geometry(pixels, *args, **kwargs):
            observed.append(pixels.getpixel((0, 0)))
            self.assertEqual(pixels.size, (10, 6))
            return render_geometry(pixels, *args, **kwargs)
        with patch('image_lab_ui.edit_color.render_geometry', side_effect=geometry):
            result = render_color_geometry(image, recipe, orientation=6, policy='srgb-v1')
        self.keep(result.image)
        self.assertTrue(all(abs(channel - 188) <= 1 for channel in observed[0]))
        self.assertEqual(result.image.size, (recipe.result_size.width, recipe.result_size.height))
        self.assertEqual(set(result.image.info), {'icc_profile'})
        self.assertEqual(image.info['exif'], b'private source metadata')

    def test_conversion_happens_before_nonlinear_reduction(self):
        image = self.keep(Image.frombytes('RGB', (2, 1), bytes((0, 0, 0, 255, 255, 255))))
        image.info['icc_profile'] = linear_rgb_profile()
        result = render_color_geometry(image, EditRecipe.original(2, 1).resized_width(1),
                                       orientation=1, policy='srgb-v1')
        self.keep(result.image)
        # Convert endpoints first, then average encoded samples: ~128, not the
        # ~188 produced by averaging linear samples before sRGB conversion.
        for channel in result.image.getpixel((0, 0)):
            self.assertLessEqual(abs(channel - 128), 1)

    def test_preview_full_resolution_and_profile_remain_distinct(self):
        image = self.keep(Image.new('RGBA', (2600, 1300), (128, 128, 128, 128)))
        image.info['icc_profile'] = linear_rgb_profile()
        recipe = EditRecipe.original(2600, 1300)
        full = render_color_geometry(image, recipe, orientation=1, policy='srgb-v1')
        preview = render_color_geometry(image, recipe, orientation=1, policy='srgb-v1', preview_longest=512)
        self.keep(full.image); self.keep(preview.image)
        self.assertEqual(full.full_resolution_image().size, (2600, 1300))
        self.assertEqual(preview.image.size, (512, 256))
        with self.assertRaises(ValueError):
            preview.full_resolution_image()
        self.assertEqual(full.color, preview.color)
        self.assertEqual(full.image.getpixel((10, 10))[3], 128)
        self.assertEqual(preview.image.getpixel((10, 10))[3], 128)

    def test_public_imagescope_color_and_measurements_match_all_orientations(self):
        image = self.keep(Image.frombytes('RGB', (3, 2), bytes(v for value in (16, 32, 64, 96, 128, 192) for v in (value,) * 3)))
        image.info['icc_profile'] = linear_rgb_profile()
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                exif = Image.Exif(); exif[274] = orientation
                source = encoded(image, exif=exif)
                reference = analyze(AnalysisRequest(source, task='inspect', color_policy='srgb-v1'))
                self.assertEqual(reference['status'], 'ok', reference['error'])
                size = (2, 3) if orientation >= 5 else (3, 2)
                rendered = render_color_geometry(image, EditRecipe.original(*size), orientation=orientation, policy='srgb-v1')
                try:
                    actual = analyze(AnalysisRequest(encoded(rendered.image), task='inspect', color_policy='srgb-v1'))
                    self.assertEqual(actual['status'], 'ok', actual['error'])
                    self.assertEqual(actual['measurements'], reference['measurements'])
                    provider = reference['provenance']['preprocessing']['color_management']
                    for field in ('policy', 'assume_srgb', 'status', 'source_interpretation', 'output_color_space',
                                  'rendering_intent', 'black_point_compensation', 'transform_optimization',
                                  'pillow_version', 'littlecms_version'):
                        self.assertEqual(rendered.color.to_dict()[field], provider[field])
                finally:
                    rendered.image.close()

    def test_public_imagescope_rejects_the_same_invalid_profile(self):
        image = self.keep(Image.new('RGB', (3, 2), 'red'))
        image.info['icc_profile'] = b'broken'
        result = analyze(AnalysisRequest(encoded(image), task='inspect', color_policy='srgb-v1', assume_srgb=True))
        with self.assertRaises(EditColorError) as error:
            prepare_color_pixels(image, policy='srgb-v1', assume_srgb=True)
        self.assertEqual(error.exception.code, result['error']['code'])


if __name__ == '__main__':
    unittest.main()
