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


if __name__ == "__main__":
    unittest.main()
