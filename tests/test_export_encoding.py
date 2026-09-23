import io
from copy import deepcopy
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageCms, PngImagePlugin
from image_lab_ui.edit_process import prepare_source, render_source
from image_lab_ui.edit_protocol import EditWorkerError
from image_lab_ui.edit_recipe import EditRecipe, Crop
from image_lab_ui.export_encoding import encode_copy
from test_edit_color import linear_rgb_profile

ROOT = Path(__file__).resolve().parents[1]


class EncodingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT/'results'); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'source.png'

    def source(self, mode='RGBA', size=(48,32), *, profile=None, orientation=1, tagged=True):
        info = PngImagePlugin.PngInfo()
        if tagged: info.add(b'sRGB', b'\0')
        info.add_text('XML:com.adobe.xmp', '<GPSLatitude>private</GPSLatitude>')
        exif = Image.Exif(); exif[274] = orientation; exif[315] = 'private author'
        with Image.new(mode, size, (80,120,160,128) if mode=='RGBA' else (80,120,160)) as image:
            image.save(self.path, pnginfo=info, exif=exif, icc_profile=profile)
        self.before = self.path.read_bytes(), self.path.stat().st_mtime_ns
        return prepare_source(self.path)

    def encode(self, source, recipe=None, format='PNG', *, lossless=False, matte=None, assume=False, **kwargs):
        recipe = recipe or EditRecipe.original(*source.oriented_size.as_list())
        return encode_copy(source, recipe, color_policy='srgb-v1', assume_srgb=assume,
            options={'format':format,'quality':95,'lossless':lossless,'matte':matte}, **kwargs)

    def test_formats_alpha_tagging_metadata_and_original_preservation(self):
        source = self.source()
        for format, lossless in (('PNG',False),('WEBP',True),('WEBP',False),('JPEG',False)):
            with self.subTest(format=format,lossless=lossless):
                encoded = self.encode(source,format=format,lossless=lossless,matte='#ffffff' if format=='JPEG' else None)
                encoded.verify_staging(io.BytesIO(encoded.data))
                with Image.open(io.BytesIO(encoded.data)) as image:
                    image.load(); self.assertEqual(image.size,(48,32)); self.assertEqual(image.format,format)
                    self.assertFalse(image.getexif())
                    self.assertNotIn('XML:com.adobe.xmp',image.info); self.assertNotIn('xmp',image.info)
                    if format=='PNG': self.assertEqual(image.info.get('srgb'),0)
                    else:
                        profile=ImageCms.ImageCmsProfile(io.BytesIO(image.info['icc_profile']))
                        self.assertIn('sRGB',ImageCms.getProfileDescription(profile))
                    if format!='JPEG': self.assertEqual(image.convert('RGBA').getpixel((0,0))[3],128)
                    else:
                        expected=tuple(round(c*128/255+255*127/255) for c in (80,120,160))
                        self.assertLessEqual(max(abs(a-b) for a,b in zip(image.getpixel((10,10)),expected)),3)
        self.assertEqual((self.path.read_bytes(),self.path.stat().st_mtime_ns),self.before)

    def test_full_resolution_never_preview_and_all_exif_orientations(self):
        source=self.source('RGB',(2500,12))
        result=self.encode(source)
        with Image.open(io.BytesIO(result.data)) as image: self.assertEqual(image.size,(2500,12))
        for orientation in range(1,9):
            source=self.source('RGB',orientation=orientation)
            recipe=EditRecipe.original(*source.oriented_size.as_list()).with_crop(Crop(2,3,20,25)).rotated(1).flipped(horizontal=True).resized_width(11)
            result=self.encode(source,recipe)
            full=render_source(source,recipe,preview_longest=None,color_policy='srgb-v1')
            with Image.open(io.BytesIO(result.data)) as image:
                self.assertEqual(image.size,tuple(recipe.result_size.as_list()))
                self.assertEqual(image.tobytes(),full.full_resolution_pixels())

    def test_profiled_encoded_pixels_match_managed_preview_and_linear_reference(self):
        source=self.source('RGB',profile=linear_rgb_profile())
        recipe=EditRecipe.original(*source.oriented_size.as_list())
        frame=render_source(source,recipe,color_policy='srgb-v1')
        for format,lossless in (('PNG',False),('WEBP',True),('JPEG',False)):
            result=self.encode(source,format=format,lossless=lossless)
            with Image.open(io.BytesIO(result.data)) as image:
                image.load()
                for actual,original in zip(image.getpixel((16,16)),(80,120,160)):
                    expected=round(255*(1.055*(original/255)**(1/2.4)-.055))
                    self.assertLessEqual(abs(actual-expected),3 if format=='JPEG' else 1)
                if format!='JPEG': self.assertEqual(image.tobytes(),frame.pixels)
                self.assertIn('icc_profile',image.info)

    def test_explicit_consent_invalid_profiles_and_jpeg_matte(self):
        source=self.source(tagged=False)
        with self.assertRaises(EditWorkerError): self.encode(source)
        self.encode(source,assume=True)
        with self.assertRaises(EditWorkerError): self.encode(source,format='JPEG',assume=True)
        source=self.source(profile=b'broken')
        with self.assertRaises(EditWorkerError): self.encode(source,assume=True)

    def test_options_and_returned_provenance_fail_closed(self):
        from image_lab_ui.export_encoding import validate_options
        options={'format':'PNG','quality':90,'lossless':False,'matte':None}
        for bad in ({'quality':True},{'quality':96},{'lossless':True},{'matte':'#ffffff'},{'format':'TIFF'}):
            with self.assertRaises(ValueError): validate_options(options | bad)
        source=self.source(); encoded=self.encode(source)
        bad=deepcopy(encoded.info); bad['color']['output_color_space']='unknown'
        with patch('image_lab_ui.export_encoding.request_payload',return_value=(bad,encoded.data)):
            with self.assertRaises(EditWorkerError) as caught: self.encode(source)
        self.assertEqual(caught.exception.code,'protocol_error')

    def test_source_change_cancellation_and_staging_tamper(self):
        source=self.source()
        with self.assertRaises(EditWorkerError) as caught: self.encode(source,cancelled=lambda:True)
        self.assertEqual(caught.exception.code,'cancelled')
        result=self.encode(source)
        with self.assertRaises(ValueError): result.verify_staging(io.BytesIO(result.data+b'changed'))
        self.path.write_bytes(b'changed')
        with self.assertRaises(EditWorkerError) as caught: self.encode(source)
        self.assertEqual(caught.exception.code,'source_changed')


if __name__=='__main__': unittest.main()
