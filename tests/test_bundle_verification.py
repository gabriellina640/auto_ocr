import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
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

    def test_main_writes_bundle_error_log_when_verification_fails(self):
        error = RuntimeError("PyMuPDF verification failed")

        with TemporaryDirectory() as temporary_directory:
            with (
                patch.object(app, "verify_pymupdf_bundle", side_effect=error),
                patch.object(app.sys, "argv", ["app.py", "--verify-bundle"]),
                patch.object(app.Path, "cwd", return_value=Path(temporary_directory)),
            ):
                with self.assertRaisesRegex(RuntimeError, "PyMuPDF verification failed"):
                    app.main()

            error_log = Path(temporary_directory) / app.BUNDLE_VERIFICATION_ERROR_LOG
            self.assertIn(
                "RuntimeError: PyMuPDF verification failed",
                error_log.read_text(encoding="utf-8"),
            )

    def test_dependency_loader_writes_bundle_error_log_when_import_fails(self):
        error = RuntimeError("PyMuPDF import failed")

        with TemporaryDirectory() as temporary_directory:
            with (
                patch.object(
                    app,
                    "load_application_dependencies",
                    side_effect=error,
                    create=True,
                ),
                patch.object(app.sys, "argv", ["app.py", "--verify-bundle"]),
                patch.object(app.Path, "cwd", return_value=Path(temporary_directory)),
            ):
                with self.assertRaisesRegex(RuntimeError, "PyMuPDF import failed"):
                    app.load_application_dependencies_with_bundle_diagnostics()

            error_log = Path(temporary_directory) / app.BUNDLE_VERIFICATION_ERROR_LOG
            self.assertIn(
                "RuntimeError: PyMuPDF import failed",
                error_log.read_text(encoding="utf-8"),
            )

    def test_main_preserves_verification_error_when_error_logging_fails(self):
        error = RuntimeError("PyMuPDF verification failed")

        with (
            patch.object(app, "verify_pymupdf_bundle", side_effect=error),
            patch.object(app.sys, "argv", ["app.py", "--verify-bundle"]),
            patch.object(
                app.traceback,
                "format_exc",
                side_effect=RuntimeError("Unable to write diagnostic"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "PyMuPDF verification failed"):
                app.main()


if __name__ == "__main__":
    unittest.main()
