"""Extracted-wheel publication smoke, not product encoding/color acceptance."""
import io
import json
from pathlib import Path
import sys
import tempfile

from PIL import Image
from image_lab_ui import export_publication as module
from image_lab_ui.edit_process import prepare_source


def main():
    # Runner uses the extracted wheel as cwd and PYTHONPATH, not the checkout.
    assert Path(module.__file__).resolve().parent.parent == Path.cwd().resolve(), module.__file__
    with tempfile.TemporaryDirectory(prefix='publication-smoke-', dir=Path(sys.argv[1]).resolve()) as temporary:
        root = Path(temporary)
        source = root / 'source.png'
        with Image.new('RGB', (12, 8), 'red') as image:
            image.save(source)
        before = source.read_bytes(), source.stat().st_mtime_ns
        snapshot = prepare_source(source)
        # Controlled tiny encoded fixture only. A resource-bounded production
        # encoder, color tagging/alpha and metadata rules remain a later slice.
        buffer = io.BytesIO()
        with Image.new('RGB', (6, 4), 'blue') as fixture:
            fixture.save(buffer, format='PNG')
        def verify(stream):
            with Image.open(stream) as image:
                assert image.format == 'PNG' and image.size == (6, 4)
                image.verify()
        with module.CopyPublication(snapshot, root, 'copy.png', 'PNG', is_reserved=lambda path: False) as transaction:
            transaction.write(buffer.getvalue())
            assert sorted(path.name for path in root.iterdir()) == ['source.png']
            receipt = transaction.publish(verify)
        assert receipt.published and receipt.path_confirmed and receipt.directory_synced
        assert (root / 'copy.png').read_bytes() == buffer.getvalue()
        try:
            module.CopyPublication(snapshot, root, 'copy.png', 'PNG', is_reserved=lambda path: False)
        except FileExistsError:
            pass
        else:
            raise AssertionError('Existing copy was not protected.')
        assert (source.read_bytes(), source.stat().st_mtime_ns) == before
        print(json.dumps({'packaged_publication': True, 'module': module.__file__,
                          'anonymous_staging': True, 'collision_refused': True,
                          'source_unchanged': True, 'directory_synced': receipt.directory_synced,
                          'warnings': receipt.warnings, 'encoded_color_acceptance': False}))


if __name__ == '__main__': main()
