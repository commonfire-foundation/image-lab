from dataclasses import replace
from itertools import product
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from image_lab_ui.edit_recipe import Crop, EditRecipe, Size
from image_lab_ui.edit_render import preview_size, render_geometry


def matrix(image):
    return [[image.getpixel((x, y))[0] for x in range(image.width)] for y in range(image.height)]


def fixture():
    image = Image.new('RGB', (3, 2))
    image.putdata([(number, 0, 0) for number in range(1, 7)])
    return image


class RenderTests(unittest.TestCase):
    def test_all_exif_orientations_once_without_changing_source(self):
        image = fixture()
        exif = Image.Exif()
        exif[274] = 6
        image.info['exif'] = exif.tobytes()
        before, info = image.tobytes(), dict(image.info)
        expected = {
            1: [[1, 2, 3], [4, 5, 6]], 2: [[3, 2, 1], [6, 5, 4]],
            3: [[6, 5, 4], [3, 2, 1]], 4: [[4, 5, 6], [1, 2, 3]],
            5: [[1, 4], [2, 5], [3, 6]], 6: [[4, 1], [5, 2], [6, 3]],
            7: [[6, 3], [5, 2], [4, 1]], 8: [[3, 6], [2, 5], [1, 4]],
        }
        for orientation, rows in expected.items():
            with self.subTest(orientation=orientation):
                recipe = EditRecipe.original(len(rows[0]), len(rows))
                rendered = render_geometry(image, recipe, orientation=orientation)
                self.addCleanup(rendered.image.close)
                self.assertEqual(matrix(rendered.image), rows)
                self.assertEqual(rendered.image.getexif().get(274), None)
        self.assertEqual(image.tobytes(), before)
        self.assertEqual(image.info, info)

    def test_crop_uses_oriented_source_pixels(self):
        image = fixture()
        recipe = EditRecipe.original(2, 3).with_crop(Crop(0, 1, 2, 3))
        rendered = render_geometry(image, recipe, orientation=6)
        self.addCleanup(rendered.image.close)
        self.assertEqual(matrix(rendered.image), [[5, 2], [6, 3]])
        recipe = recipe.with_crop(Crop(1, 2, 2, 3))
        rendered = render_geometry(image, recipe, orientation=6)
        self.addCleanup(rendered.image.close)
        self.assertEqual(matrix(rendered.image), [[3]])

    def test_pixel_centers_match_coordinate_contract_for_every_transform(self):
        image = Image.new('RGB', (6, 4))
        image.putdata([(value, 0, 0) for value in range(24)])
        for turns, horizontal, vertical in product(range(4), (False, True), (False, True)):
            recipe = replace(EditRecipe.original(6, 4).with_crop(Crop(1, 1, 5, 4)),
                             quarter_turns=turns, flip_horizontal=horizontal, flip_vertical=vertical)
            rendered = render_geometry(image, recipe, orientation=1)
            try:
                for y, x in product(range(1, 4), range(1, 5)):
                    rx, ry = recipe.source_to_result(x + 0.5, y + 0.5)
                    self.assertEqual(rendered.image.getpixel((int(rx), int(ry))), image.getpixel((x, y)))
            finally:
                rendered.image.close()

    def test_rotate_command_means_clockwise_after_prior_flips(self):
        image = fixture()
        for horizontal, vertical in product((False, True), repeat=2):
            recipe = EditRecipe.original(3, 2).flipped(horizontal=horizontal, vertical=vertical)
            first = render_geometry(image, recipe, orientation=1)
            second = render_geometry(image, recipe.rotated(), orientation=1)
            expected = first.image.transpose(Image.Transpose.ROTATE_270)
            self.assertEqual(second.image.tobytes(), expected.tobytes())
            first.image.close()
            second.image.close()
            expected.close()

    def test_preview_is_bounded_and_cannot_be_used_for_export(self):
        image = Image.new('RGB', (2600, 1300), 'blue')
        recipe = EditRecipe.original(2600, 1300)
        preview = render_geometry(image, recipe, orientation=1, preview_longest=512)
        self.addCleanup(preview.image.close)
        self.assertEqual(preview.image.size, (512, 256))
        self.assertEqual(preview.output_size, Size(2600, 1300))
        with self.assertRaises(ValueError):
            preview.full_resolution_image()
        full = render_geometry(image, recipe, orientation=1)
        self.addCleanup(full.image.close)
        self.assertEqual(full.full_resolution_image().size, (2600, 1300))
        self.assertEqual(full.image.getpixel((2599, 1299)), (0, 0, 255))
        # Even a preview that happened to fit without reduction isn't an export.
        small = render_geometry(fixture(), EditRecipe.original(3, 2), orientation=1, preview_longest=512)
        self.addCleanup(small.image.close)
        with self.assertRaises(ValueError):
            small.full_resolution_image()

    def test_resize_uses_recipe_dimensions_after_rotation(self):
        image = Image.new('RGB', (120, 80), 'red')
        recipe = EditRecipe.original(120, 80).with_crop(Crop(10, 10, 110, 70)).rotated().resized_height(50)
        full = render_geometry(image, recipe, orientation=1)
        self.addCleanup(full.image.close)
        self.assertEqual(full.image.size, (30, 50))
        preview = render_geometry(image, recipe, orientation=1, preview_longest=20)
        self.addCleanup(preview.image.close)
        self.assertEqual(preview.image.size, (12, 20))
        self.assertEqual(preview.output_size, full.output_size)

    def test_alpha_resize_does_not_mix_hidden_rgb_into_visible_pixels(self):
        image = Image.new('RGBA', (2, 1))
        image.putdata([(255, 0, 0, 0), (0, 0, 255, 255)])
        before = image.tobytes()
        recipe = EditRecipe.original(2, 1).with_upscale(True).resized_width(8)
        result = render_geometry(image, recipe, orientation=1)
        self.addCleanup(result.image.close)
        self.assertEqual(result.image.mode, 'RGBA')
        self.assertTrue(any(result.image.getpixel((x, 0))[3] == 0 for x in range(8)))
        for x in range(8):
            red, green, blue, alpha = result.image.getpixel((x, 0))
            if alpha:
                self.assertEqual((red, green, blue), (0, 0, 255))
        self.assertEqual(image.tobytes(), before)

    def test_output_is_independent_and_only_carries_profile_bytes(self):
        image = fixture()
        image.info.update(icc_profile=b'opaque-test-profile-bytes', exif=b'old', comment='private')
        result = render_geometry(image, EditRecipe.original(3, 2), orientation=1)
        self.addCleanup(result.image.close)
        self.assertEqual(result.image.info, {'icc_profile': b'opaque-test-profile-bytes'})
        result.image.putpixel((0, 0), (99, 99, 99))
        self.assertEqual(image.getpixel((0, 0)), (1, 0, 0))
        self.assertEqual(image.info['comment'], 'private')

    def test_lazy_file_is_rejected_and_loaded_original_is_not_modified(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory) / 'original.png'
            fixture().save(path)
            before, stamp = path.read_bytes(), path.stat().st_mtime_ns
            with Image.open(path) as image:
                with self.assertRaisesRegex(ValueError, 'Decode and isolate'):
                    render_geometry(image, EditRecipe.original(3, 2), orientation=1)
                image.load()
                result = render_geometry(image, EditRecipe.original(3, 2).rotated(), orientation=1)
                result.image.close()
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(path.stat().st_mtime_ns, stamp)

    def test_invalid_input_is_not_silently_converted(self):
        recipe = EditRecipe.original(3, 2)
        for mode in ('L', 'P', 'CMYK', 'I;16', 'F'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                render_geometry(Image.new(mode, (3, 2)), recipe, orientation=1)
        for orientation in (0, 9, None, True, '1'):
            with self.assertRaises(ValueError):
                render_geometry(fixture(), recipe, orientation=orientation)
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            render_geometry(fixture(), recipe, orientation=6)
        image = fixture()
        image.info['icc_profile'] = b'x' * (1024 * 1024 + 1)
        with self.assertRaisesRegex(ValueError, 'ICC'):
            render_geometry(image, recipe, orientation=1)
        for bound in (0, 2049, True, 1.5):
            with self.assertRaises(ValueError):
                preview_size(Size(300, 200), bound)
        self.assertEqual(preview_size(Size(1, 10000), 128), Size(1, 128))


if __name__ == '__main__':
    unittest.main()
