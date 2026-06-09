import unittest

from PIL import Image

import app


class CompressionProfileTests(unittest.TestCase):
    def test_default_profile_is_faithful_png_at_default_dpi(self):
        profile = app.COMPRESSION_PROFILES["faithful"]

        self.assertEqual(profile.key, "faithful")
        self.assertEqual(profile.dpi, app.DEFAULT_DPI)
        self.assertEqual(profile.image_format, "PNG")
        self.assertIsNone(profile.jpeg_quality)

    def test_reduce_size_profile_uses_strong_jpeg(self):
        faithful = app.COMPRESSION_PROFILES["faithful"]
        compressed = app.COMPRESSION_PROFILES["compressed"]

        self.assertEqual(compressed.image_format, "JPEG")
        self.assertLess(compressed.dpi, faithful.dpi)
        self.assertLess(compressed.jpeg_quality, 70)

    def test_checkbox_profile_mapping(self):
        self.assertEqual(app.compression_profile_for_reduce_size(False).key, "faithful")
        self.assertEqual(app.compression_profile_for_reduce_size(True).key, "compressed")

    def test_make_ocr_image_path_uses_profile_format_suffix(self):
        base = app.Path("page_00001")

        self.assertEqual(app.make_ocr_image_path(base, app.COMPRESSION_PROFILES["faithful"]).suffix, ".png")
        self.assertEqual(app.make_ocr_image_path(base, app.COMPRESSION_PROFILES["compressed"]).suffix, ".jpg")

    def test_prepare_ocr_image_keeps_dimensions_for_faithful_profile(self):
        image = Image.new("RGB", (100, 50), "white")
        prepared = app.prepare_ocr_image(image, app.COMPRESSION_PROFILES["faithful"])

        self.assertEqual(prepared.size, (100, 50))
        self.assertEqual(prepared.mode, "RGB")

    def test_prepare_ocr_image_downsamples_compressed_profile(self):
        image = Image.new("RGB", (300, 150), "white")
        prepared = app.prepare_ocr_image(image, app.COMPRESSION_PROFILES["compressed"])

        self.assertLess(prepared.width, image.width)
        self.assertLess(prepared.height, image.height)


if __name__ == "__main__":
    unittest.main()
