"""Run from an extracted wheel directory with its path first on PYTHONPATH."""
import hashlib
import json
from pathlib import Path
import tempfile

from PIL import Image, ImageCms
from image_lab_ui import edit_worker
from image_lab_ui.edit_process import prepare_source, render_source
from image_lab_ui.edit_protocol import EditWorkerError, PROTOCOL_VERSION
from image_lab_ui.edit_recipe import EditRecipe, Size


def main():
    root = Path.cwd()
    assert Path(edit_worker.__file__).resolve().is_relative_to(root)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        path = Path(directory) / 'source.png'
        with Image.new('RGBA', (2600, 4), (128, 64, 32, 100)) as image:
            image.save(path, icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        original = path.read_bytes()
        stamp = path.stat().st_mtime_ns
        source = prepare_source(path)
        recipe = EditRecipe.original(2600, 4)
        full = render_source(source, recipe, preview_longest=None, color_policy='srgb-v1', generation=9)
        preview = render_source(source, recipe, preview_longest=512, color_policy='srgb-v1', generation=10)
        assert PROTOCOL_VERSION == 2
        assert full.size == Size(2600, 4) and len(full.full_resolution_pixels()) == 2600 * 4 * 4
        assert full.pixels == bytes((128, 64, 32, 100)) * 2600 * 4
        assert preview.size.width == 512
        assert full.color.status == preview.color.status == 'converted'
        assert full.color.transform_optimization == 'disabled'
        assert full.icc_profile[36:40] == b'acsp'
        assert full.generation == 9 and preview.generation == 10
        try:
            preview.full_resolution_pixels()
            raise AssertionError('Preview accepted as full resolution')
        except EditWorkerError as error:
            assert error.code == 'preview_not_exportable'
        assert path.read_bytes() == original and path.stat().st_mtime_ns == stamp
        assert source.sha256 == hashlib.sha256(original).hexdigest()
        print(json.dumps({'packaged_color_worker': True, 'protocol': PROTOCOL_VERSION,
                          'worker_module': edit_worker.__file__, 'cms': full.color.littlecms_version}))


if __name__ == '__main__':
    main()
