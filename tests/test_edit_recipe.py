from dataclasses import FrozenInstanceError, replace
from itertools import product
import json
import unittest

from image_lab_ui.edit_recipe import Crop, EditHistory, EditRecipe, FitTransform, Size


class RecipeTests(unittest.TestCase):
    def test_original_and_serialization_are_immutable(self):
        recipe = EditRecipe.original(1200, 800)
        self.assertEqual(recipe.result_size, Size(1200, 800))
        self.assertEqual(EditRecipe.from_dict(json.loads(json.dumps(recipe.to_dict()))), recipe)
        with self.assertRaises(FrozenInstanceError):
            recipe.quarter_turns = 2
        data = recipe.to_dict()
        data['crop'][0] = 99
        self.assertEqual(recipe.crop.left, 0)

    def test_crop_resets_resize_and_respects_original_bounds(self):
        recipe = EditRecipe.original(1200, 800).rotated().resized_width(400)
        cropped = recipe.with_crop(Crop(10, 20, 110, 220))
        self.assertIsNone(cropped.output_size)
        self.assertEqual(cropped.natural_size, Size(200, 100))
        self.assertEqual(cropped.quarter_turns, 1)
        self.assertEqual(recipe.output_size, Size(400, 600))
        with self.assertRaises(ValueError):
            recipe.with_crop(Crop(0, 0, 1201, 800))

    def test_rotation_resize_and_flip_composition(self):
        recipe = EditRecipe.original(1200, 800).resized_width(600).flipped(horizontal=True)
        rotated = recipe.rotated()
        self.assertEqual(rotated.output_size, Size(400, 600))
        self.assertFalse(rotated.flip_horizontal)
        self.assertTrue(rotated.flip_vertical)
        self.assertEqual(rotated.rotated(3), recipe)
        self.assertEqual(recipe.rotated(-1), recipe.rotated(3))
        self.assertEqual(recipe.flipped(horizontal=True).flipped(horizontal=True), recipe)

    def test_aspect_presets_are_centered_exact_and_display_oriented(self):
        recipe = EditRecipe.original(1200, 800)
        for numerator, denominator in [(1, 1), (4, 3), (3, 2), (16, 9), (9, 16), (21, 9)]:
            for turns in range(4):
                with self.subTest(ratio=(numerator, denominator), turns=turns):
                    cropped = recipe.rotated(turns).with_aspect(numerator, denominator)
                    size = cropped.natural_size
                    self.assertEqual(size.width * denominator, size.height * numerator)
                    self.assertLessEqual(abs(cropped.crop.left - (1200 - cropped.crop.right)), 1)
                    self.assertLessEqual(abs(cropped.crop.top - (800 - cropped.crop.bottom)), 1)
        with self.assertRaises(ValueError):
            EditRecipe.original(2, 2).with_aspect(16, 9)

    def test_resize_is_aspect_locked_and_upscale_is_explicit(self):
        recipe = EditRecipe.original(101, 67)
        self.assertEqual(recipe.resized_width(50).result_size, Size(50, 33))
        self.assertEqual(recipe.resized_height(33).result_size, Size(50, 33))
        self.assertEqual(recipe.resized_percent(50).result_size, Size(51, 34))
        self.assertEqual(recipe.resized_percent(0.01).result_size, Size(1, 1))
        with self.assertRaises(ValueError):
            recipe.resized_width(102)
        self.assertEqual(recipe.with_upscale(True).resized_width(202).result_size, Size(202, 134))
        with self.assertRaises(ValueError):
            recipe.with_upscale(True).resized_width(202).with_upscale(False)
        with self.assertRaises(ValueError):
            replace(recipe, output_size=Size(50, 10))
        for bad in (False, 0, -1, float('nan'), float('inf'), 10001, 10 ** 1000, '50'):
            with self.subTest(bad=str(bad)[:20]), self.assertRaises(ValueError):
                recipe.resized_percent(bad)

    def test_reject_invalid_geometry_and_serialized_contract(self):
        for dimensions in [(0, 1), (-1, 2), (True, 5), (1.0, 2), (10000, 10000)]:
            with self.subTest(dimensions=dimensions), self.assertRaises(ValueError):
                Size(*dimensions)
        for bounds in [(0, 0, 0, 5), (0, 0, 5, 0), (-1, 0, 1, 1), (False, 0, 2, 2)]:
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                Crop(*bounds)
        base = EditRecipe.original(40, 20).to_dict()
        for key, value in [('version', 2), ('version', True), ('quarter_turns', 4),
                           ('quarter_turns', -1), ('quarter_turns', False),
                           ('flip_horizontal', 1), ('flip_vertical', 'false'),
                           ('allow_upscale', 0), ('crop', [0, 0, 41, 20]),
                           ('source_size', [40]), ('output_size', []), ('crop', (0, 0, 40, 20))]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                EditRecipe.from_dict(dict(base, **{key: value}))
        for invalid in (None, [], {}, dict(base, extra=1)):
            with self.assertRaises(ValueError):
                EditRecipe.from_dict(invalid)

    def test_coordinate_round_trips_all_rotations_flips_and_resizes(self):
        original = EditRecipe.original(50, 30).with_crop(Crop(7, 3, 43, 27))
        for turns, horizontal, vertical in product(range(4), (False, True), (False, True)):
            recipe = replace(original, quarter_turns=turns, flip_horizontal=horizontal, flip_vertical=vertical)
            recipe = recipe.resized_percent(50)
            for x, y in [(7, 3), (43, 3), (43, 27), (7, 27), (10.5, 9.25)]:
                with self.subTest(turns=turns, flips=(horizontal, vertical), point=(x, y)):
                    point = recipe.source_to_result(x, y)
                    result = recipe.result_to_source(*point)
                    self.assertAlmostEqual(result[0], x)
                    self.assertAlmostEqual(result[1], y)
        with self.assertRaises(ValueError):
            original.source_to_result(0, 0)
        with self.assertRaises(ValueError):
            original.result_to_source(-1, 1)
        with self.assertRaises(ValueError):
            original.source_to_result(float('nan'), 5)

    def test_known_clockwise_corner_mapping(self):
        recipe = EditRecipe.original(100, 60).with_crop(Crop(10, 5, 90, 55)).rotated()
        self.assertEqual(recipe.source_to_result(10, 5), (50, 0))
        self.assertEqual(recipe.source_to_result(90, 55), (0, 80))
        self.assertEqual(recipe.result_to_source(25, 40), (50, 30))


class FitTransformTests(unittest.TestCase):
    def test_fit_letterbox_and_round_trip(self):
        fit = FitTransform(Size(1200, 600), 600, 600)
        self.assertEqual(fit.scale, 0.5)
        self.assertEqual(fit.offset, (0, 150))
        self.assertEqual(fit.to_view(600, 300), (300, 300))
        self.assertEqual(fit.to_image(300, 300), (600, 300))
        with self.assertRaises(ValueError):
            fit.to_image(300, 100)
        self.assertEqual(fit.to_image(-20, 900, clamp=True), (0, 600))
        for viewport in [(900, 600), (1280, 820), (300, 1000), (10.5, 30.25)]:
            fit = FitTransform(Size(300, 1700), *viewport)
            x, y = fit.to_image(*fit.to_view(75, 850))
            self.assertAlmostEqual(x, 75)
            self.assertAlmostEqual(y, 850)

    def test_qt_logical_mapping_does_not_double_apply_dpr(self):
        fit = FitTransform(Size(1200, 600), 600, 600)
        for dpr in (1, 1.5, 2, 3):
            physical_point = (300 * dpr, 300 * dpr)
            logical_point = tuple(value / dpr for value in physical_point)
            self.assertEqual(fit.to_image(*logical_point), (600, 300))

    def test_invalid_values(self):
        for value in (0, -1, False, float('nan'), float('inf'), '100'):
            with self.assertRaises(ValueError):
                FitTransform(Size(100, 100), value, 100)
        fit = FitTransform(Size(1, 1), 100, 100)
        with self.assertRaises(ValueError):
            fit.to_image(float('inf'), 0, clamp=True)


class HistoryTests(unittest.TestCase):
    def test_undo_redo_branch_reset_and_export_revision(self):
        original = EditRecipe.original(100, 60)
        history = EditHistory(original)
        self.assertFalse(history.dirty)
        a, b = original.rotated(), original.rotated(2)
        self.assertTrue(history.commit(a))
        self.assertFalse(history.commit(a))  # Duplicate gesture is not a new step.
        history.commit(b)
        history.mark_exported(a)  # A late completion must not mark b as saved.
        self.assertTrue(history.dirty)
        self.assertEqual(history.undo(), a)
        self.assertFalse(history.dirty)
        self.assertEqual(history.redo(), b)
        history.undo()
        history.commit(original.flipped(horizontal=True))
        self.assertFalse(history.can_redo)
        self.assertEqual(history.reset(), original)
        self.assertTrue(history.dirty)  # Export checkpoint is still a.
        history.mark_exported(original)
        self.assertFalse(history.dirty)
        history.undo()
        self.assertTrue(history.dirty)

    def test_bounded_history_retains_reset_target(self):
        original = EditRecipe.original(1000, 600)
        history = EditHistory(original, limit=3)
        for width in range(900, 910):
            history.commit(original.resized_width(width))
        undos = 0
        while history.can_undo:
            history.undo()
            undos += 1
        self.assertEqual(undos, 2)
        self.assertEqual(history.reset(), original)
        self.assertFalse(history.dirty)

    def test_reject_invalid_history_changes(self):
        original = EditRecipe.original(100, 60)
        for limit in (0, 101, False, 1.5):
            with self.assertRaises(ValueError):
                EditHistory(original, limit)
        history = EditHistory(original)
        for recipe in (None, EditRecipe.original(60, 100)):
            with self.assertRaises(ValueError):
                history.commit(recipe)
            with self.assertRaises(ValueError):
                history.mark_exported(recipe)


if __name__ == '__main__':
    unittest.main()
