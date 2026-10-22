import runpy
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_HOOK = ROOT / "runtime_hooks" / "bundle_verification_diagnostics.py"
ERROR_LOG = "autoocr-bundle-verification-error.log"


class RuntimeBundleDiagnosticsTests(unittest.TestCase):
    def test_redirects_early_errors_to_a_log_for_bundle_verification(self):
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        with TemporaryDirectory() as temporary_directory:
            with (
                patch.object(sys, "argv", ["AutoOCRPDF.exe", "--verify-bundle"]),
                patch.object(Path, "cwd", return_value=Path(temporary_directory)),
            ):
                try:
                    runpy.run_path(str(RUNTIME_HOOK))
                    print("runtime hook started", file=sys.stderr)
                    sys.stderr.flush()
                finally:
                    redirected_stdout = sys.stdout
                    redirected_stderr = sys.stderr
                    sys.stdout = original_stdout
                    sys.stderr = original_stderr
                    if redirected_stdout is redirected_stderr:
                        redirected_stdout.close()

            error_log = Path(temporary_directory) / ERROR_LOG
            self.assertIn("runtime hook started", error_log.read_text(encoding="utf-8"))

    def test_does_not_change_standard_streams_without_bundle_verification(self):
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        with patch.object(sys, "argv", ["AutoOCRPDF.exe"]):
            runpy.run_path(str(RUNTIME_HOOK))

        self.assertIs(sys.stdout, original_stdout)
        self.assertIs(sys.stderr, original_stderr)


if __name__ == "__main__":
    unittest.main()
