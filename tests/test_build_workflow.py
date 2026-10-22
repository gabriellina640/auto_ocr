import unittest
from pathlib import Path


class WindowsBuildWorkflowTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.workflow = (root / ".github/workflows/build-windows-exe.yml").read_text(
            encoding="utf-8"
        )

    def test_collects_the_pymupdf_package(self):
        self.assertIn('--collect-all "pymupdf"', self.workflow)

    def test_runs_the_packaged_bundle_check(self):
        self.assertIn('& .\\dist\\AutoOCRPDF.exe --verify-bundle', self.workflow)

    def test_pins_the_known_compatible_pymupdf_version(self):
        root = Path(__file__).resolve().parents[1]
        requirements = (root / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("PyMuPDF==1.27.2.3", requirements.splitlines())

    def test_rejects_the_unneeded_pymupdf_layout_dependency(self):
        self.assertIn('expected = "1.27.2.3"', self.workflow)
        self.assertIn('find_spec("pymupdf.layout") is not None', self.workflow)


if __name__ == "__main__":
    unittest.main()
