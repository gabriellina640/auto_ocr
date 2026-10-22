import unittest
from unittest.mock import Mock, patch

import app


class BundleVerificationTests(unittest.TestCase):
    def test_verify_pymupdf_bundle_creates_and_serializes_document(self):
        document = Mock()
        document.tobytes.return_value = b"%PDF-1.7"

        with patch.object(app.fitz, "open", return_value=document):
            self.assertEqual(app.verify_pymupdf_bundle(), 0)

        document.new_page.assert_called_once_with()
        document.tobytes.assert_called_once_with()
        document.close.assert_called_once_with()

    def test_main_verifies_bundle_without_creating_ui(self):
        with (
            patch.object(app, "verify_pymupdf_bundle", return_value=0) as verify,
            patch.object(app, "create_root_window") as create_root,
            patch.object(app, "AutoOCRApp") as auto_ocr_app,
            patch.object(app.sys, "argv", ["app.py", "--verify-bundle"]),
        ):
            self.assertEqual(app.main(), 0)

        verify.assert_called_once_with()
        create_root.assert_not_called()
        auto_ocr_app.assert_not_called()


if __name__ == "__main__":
    unittest.main()
