"""Full-source render, explicit managed encoding and decode verification in one child."""
from .editor_payload import worker_main
from .export_publication import MAX_ENCODED_BYTES


def execute(request):
    import io
    import hashlib
    from PIL import Image, ImageCms, PngImagePlugin
    from .edit_worker import execute as render, _validate_request, _check_current
    from .edit_protocol import EditWorkerError
    from .export_encoding import validate_options

    options = validate_options(request['options'])
    task = request['render']
    _validate_request(task)
    if task['operation'] != 'render' or task['preview_longest'] is not None or task['color_policy'] != 'srgb-v1':
        raise ValueError('Encoding requires a full-resolution managed render, never preview pixels.')
    source, descriptor, raster, color, profile = render(task)
    if descriptor['is_preview'] or descriptor['size'] != descriptor['output_size'] or color['output_color_space'] != 'srgb':
        raise ValueError('Cannot encode a preview or unknown color interpretation.')
    render_profile = None if profile is None else {'byte_count': len(profile), 'sha256': hashlib.sha256(profile).hexdigest()}
    image = Image.frombytes(descriptor['mode'], tuple(descriptor['size']), raster)
    del raster
    format = options['format']
    try:
        if format == 'JPEG' and image.mode == 'RGBA':
            if options['matte'] is None:
                raise ValueError('JPEG cannot preserve alpha. Choose an explicit matte color.')
            matte = Image.new('RGB', image.size, options['matte'])
            matte.paste(image, mask=image.getchannel('A'))  # Explicit encoded-sRGB8 compositing.
            image.close(); image = matte
        image.info.clear()  # No EXIF/XMP/GPS/orientation/dimensions copied from the source.
        kwargs = {}
        if format == 'PNG' and profile is None:
            metadata = PngImagePlugin.PngInfo(); metadata.add(b'sRGB', b'\0')
            kwargs['pnginfo'] = metadata
        else:
            # These pixels are already sRGB. Tag; do not transform them again.
            profile = profile or ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
            kwargs['icc_profile'] = profile
        if format == 'JPEG': kwargs.update(quality=options['quality'], subsampling=0)
        if format == 'WEBP': kwargs.update(quality=options['quality'], lossless=options['lossless'], exact=True, method=4)

        class Buffer(io.BytesIO):
            def write(self, data):
                if self.tell() + len(data) > MAX_ENCODED_BYTES:
                    raise EditWorkerError('output_limit', 'Encoded image exceeds 192 MiB.')
                return super().write(data)
        with Buffer() as output:
            image.save(output, format=format, **kwargs)
            encoded = output.getvalue()
        with Image.open(io.BytesIO(encoded)) as check:
            check.verify()
        with Image.open(io.BytesIO(encoded)) as check:
            check.load()
            if check.format != format or check.size != image.size or getattr(check, 'n_frames', 1) != 1:
                raise ValueError('Encoded format/dimensions/frame count failed verification.')
            if check.getexif() or any(key in check.info for key in ('exif', 'xmp', 'XML:com.adobe.xmp')):
                raise ValueError('Stale source metadata survived encoding.')
            if profile is not None:
                if check.info.get('icc_profile') != profile: raise ValueError('Encoded color profile mismatch.')
            elif check.info.get('srgb') != 0:
                raise ValueError('Encoded PNG is missing its sRGB declaration.')
            if format == 'PNG' or (format == 'WEBP' and options['lossless']):
                with check.convert(image.mode) as pixels:
                    if pixels.tobytes() != image.tobytes(): raise ValueError('Lossless output changed pixels or alpha.')
            if image.mode == 'RGBA':
                with check.convert('RGBA') as pixels:
                    if pixels.getchannel('A').tobytes() != image.getchannel('A').tobytes():
                        raise ValueError('Encoded transparency changed.')
        _check_current(source)
        return {'source': source.to_dict(), 'recipe': task['recipe'], 'options': options,
                'size': list(image.size), 'mode': image.mode, 'color_policy': 'srgb-v1',
                'assume_srgb': task['assume_srgb'], 'color': color, 'render_profile': render_profile, 'verified': True,
                'metadata_stripped': True}, encoded
    finally:
        image.close()


if __name__ == '__main__':
    raise SystemExit(worker_main(execute, {'render', 'options'}, MAX_ENCODED_BYTES))
