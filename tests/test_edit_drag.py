from dataclasses import replace
from itertools import product
import unittest

from image_lab_ui.edit_recipe import Crop, EditRecipe, FitTransform


class DisplayCropTests(unittest.TestCase):
    def test_inverse_crop_for_all_rotations_flips_and_resize(self):
        for turns, horizontal, vertical in product(range(4), (False, True), (False, True)):
            with self.subTest(turns=turns, horizontal=horizontal, vertical=vertical):
                recipe = replace(EditRecipe.original(200, 300).with_crop(Crop(10, 20, 110, 220)),
                                 quarter_turns=turns, flip_horizontal=horizontal, flip_vertical=vertical)
                recipe = recipe.resized_width(50)
                points = [recipe.source_to_result(x, y) for x in (30, 90) for y in (60, 160)]
                xs, ys = zip(*points)
                size = recipe.result_size
                cropped = recipe.with_display_crop(min(xs)/size.width, min(ys)/size.height,
                                                   max(xs)/size.width, max(ys)/size.height)
                self.assertEqual(cropped.crop, Crop(30, 60, 90, 160))
                self.assertIsNone(cropped.output_size)
                self.assertEqual(cropped.quarter_turns, turns)
                self.assertEqual(cropped.flip_horizontal, horizontal)
                self.assertEqual(cropped.flip_vertical, vertical)

    def test_logical_fit_mapping_across_viewports_shapes_and_dpr(self):
        for size, viewport, dpr in product(((1600, 900), (900, 1600), (4000, 40), (40, 4000)),
                                           ((520, 472), (900, 692)), (1, 1.5, 2)):
            recipe = EditRecipe.original(*size)
            fit = FitTransform(recipe.result_size, *viewport)
            # Physical pointer -> logical once. Never multiply the recipe by DPR.
            points = [fit.to_view(x, y) for x, y in ((size[0]*.25, size[1]*.25), (size[0]*.75, size[1]*.75))]
            restored = [fit.to_image(x*dpr/dpr, y*dpr/dpr) for x,y in points]
            cropped = recipe.with_display_crop(restored[0][0]/size[0], restored[0][1]/size[1],
                                               restored[1][0]/size[0], restored[1][1]/size[1])
            self.assertEqual(cropped.crop, Crop(size[0]//4, size[1]//4, size[0]*3//4, size[1]*3//4))

    def test_rounds_outward_and_full_selection_preserves_resize(self):
        recipe = EditRecipe.original(100, 80).resized_width(50)
        self.assertEqual(recipe.with_display_crop(.101, .101, .799, .899).crop, Crop(10, 8, 80, 72))
        self.assertIs(recipe.with_display_crop(0, 0, 1, 1), recipe)
        self.assertEqual(recipe.with_display_crop(.1, .1, .10000000001, .10000000001).crop, Crop(10, 8, 11, 9))
        # Values that mathematically land on exact pixel edges do not add a pixel.
        self.assertEqual(recipe.with_display_crop(.29, .25, .58, .75).crop, Crop(29, 20, 58, 60))

    def test_invalid_or_empty_selection_does_not_produce_recipe(self):
        recipe = EditRecipe.original(100, 80)
        for bounds in ((0,0,0,1), (0,1,1,0), (-.1,0,1,1), (0,0,1.1,1),
                       (0,0,float('nan'),1), (True,0,1,1), (0,0,float('inf'),1)):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                recipe.with_display_crop(*bounds)


if __name__ == '__main__':
    unittest.main()
