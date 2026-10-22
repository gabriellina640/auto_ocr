# Windows EXE PyMuPDF Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent `AutoOCRPDF.exe` from failing at startup when PyMuPDF files are absent from its one-file bundle.

**Architecture:** The application exposes a headless command that exercises PyMuPDF before any UI is created. The build explicitly collects every PyMuPDF asset and runs this command against the generated executable on the Windows runner, turning the runtime regression into a build failure.

**Tech Stack:** Python 3.12, PyMuPDF, PyInstaller, `unittest`, GitHub Actions for Windows.

---

### Task 1: Add a PyMuPDF bundle verification function

**Files:**
- Modify: `tests/test_bundle_verification.py`
- Modify: `app.py` after `bundled_resource()`

- [x] **Step 1: Write the failing test**

```python
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
```

- [x] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python -m unittest tests.test_bundle_verification.BundleVerificationTests.test_verify_pymupdf_bundle_creates_and_serializes_document -v`

Expected: FAIL with `AttributeError` because `verify_pymupdf_bundle` does not exist.

- [x] **Step 3: Implement the minimal verification function**

```python
def verify_pymupdf_bundle() -> int:
    document = fitz.open()
    try:
        document.new_page()
        document.tobytes()
    finally:
        document.close()
    return 0
```

- [x] **Step 4: Re-run the focused test**

Run: `venv/bin/python -m unittest tests.test_bundle_verification.BundleVerificationTests.test_verify_pymupdf_bundle_creates_and_serializes_document -v`

Expected: PASS.

### Task 2: Expose verification without opening Tkinter

**Files:**
- Modify: `tests/test_bundle_verification.py`
- Modify: `app.py:1803-1810`

- [x] **Step 1: Write the failing command-dispatch test**

```python
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
```

- [x] **Step 2: Run the test to verify it fails**

Run: `venv/bin/python -m unittest tests.test_bundle_verification.BundleVerificationTests.test_main_verifies_bundle_without_creating_ui -v`

Expected: FAIL because `main()` creates the UI instead of handling `--verify-bundle`.

- [x] **Step 3: Dispatch the command before creating the root window**

```python
def main() -> int:
    if "--verify-bundle" in sys.argv[1:]:
        return verify_pymupdf_bundle()

    root = create_root_window()
    AutoOCRApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Re-run the focused test**

Run: `venv/bin/python -m unittest tests.test_bundle_verification.BundleVerificationTests.test_main_verifies_bundle_without_creating_ui -v`

Expected: PASS.

### Task 3: Enforce PyMuPDF collection and execute the packaged smoke check

**Files:**
- Create: `tests/test_build_workflow.py`
- Modify: `.github/workflows/build-windows-exe.yml`
- Modify: `app.py:16`

- [x] **Step 1: Write workflow contract tests**

```python
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
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m unittest tests.test_build_workflow -v`

Expected: FAIL because the workflow does not collect PyMuPDF or run the packaged executable.

- [x] **Step 3: Update the package import and workflow**

```python
import pymupdf as fitz
```

```yaml
            --collect-all "pymupdf" `
```

```yaml
      - name: Verify packaged EXE
        shell: pwsh
        run: |
          & .\dist\AutoOCRPDF.exe --verify-bundle
          if ($LASTEXITCODE -ne 0) {
            throw "Packaged EXE failed the PyMuPDF bundle verification."
          }
```

- [x] **Step 4: Re-run workflow tests**

Run: `venv/bin/python -m unittest tests.test_build_workflow -v`

Expected: PASS.

### Task 4: Validate the complete change

**Files:**
- Verify only: `app.py`, `tests/test_bundle_verification.py`, `tests/test_build_workflow.py`, `.github/workflows/build-windows-exe.yml`

- [x] **Step 1: Run all unit tests**

Run: `venv/bin/python -m unittest discover -s tests -v`

Expected: PASS with all tests green.

- [x] **Step 2: Compile modified Python files**

Run: `venv/bin/python -m py_compile app.py tests/test_bundle_verification.py tests/test_build_workflow.py`

Expected: exit code 0.

- [x] **Step 3: Review the final diff**

Run: `git diff --check && git diff -- app.py tests/test_bundle_verification.py tests/test_build_workflow.py .github/workflows/build-windows-exe.yml`

Expected: no whitespace errors and only the planned changes.

- [ ] **Step 4: Validate the final Windows artifact**

Run: push the branch and run `Build Windows EXE` in GitHub Actions.

Expected: the `Verify packaged EXE` step exits with code 0 before the artifact is uploaded.

### Task 5: Pin PyMuPDF and reject the unused layout dependency

**Files:**
- Modify: `tests/test_build_workflow.py`
- Modify: `requirements.txt`
- Modify: `.github/workflows/build-windows-exe.yml`

- [x] **Step 1: Write failing dependency-contract tests**

```python
    def test_pins_the_known_compatible_pymupdf_version(self):
        root = Path(__file__).resolve().parents[1]
        requirements = (root / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("PyMuPDF==1.27.2.3", requirements.splitlines())

    def test_rejects_the_unneeded_pymupdf_layout_dependency(self):
        self.assertIn('expected = "1.27.2.3"', self.workflow)
        self.assertIn('find_spec("pymupdf.layout") is not None', self.workflow)
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m unittest tests.test_build_workflow -v`

Expected: FAIL because PyMuPDF is not pinned and the workflow does not verify the dependency set.

- [x] **Step 3: Pin and verify the runtime dependency**

Replace the unpinned requirement with:

```text
PyMuPDF==1.27.2.3
```

Add this workflow step immediately after dependency installation:

```yaml
      - name: Verify PyMuPDF dependency set
        shell: pwsh
        run: |
          @'
          import importlib.util
          import pymupdf

          expected = "1.27.2.3"
          actual = pymupdf.version[0]
          if actual != expected:
              raise RuntimeError(f"Expected PyMuPDF {expected}, got {actual}.")
          if importlib.util.find_spec("pymupdf.layout") is not None:
              raise RuntimeError("PyMuPDF Layout must not be included in the application build.")
          print(f"PyMuPDF {actual} verified without PyMuPDF Layout.")
          '@ | python
```

- [x] **Step 4: Re-run the dependency-contract tests**

Run: `venv/bin/python -m unittest tests.test_build_workflow -v`

Expected: PASS.

- [x] **Step 5: Run the full validation suite**

Run: `venv/bin/python -m unittest discover -s tests -v`

Expected: PASS with all tests green.

- [ ] **Step 6: Validate the Windows artifact through GitHub Actions**

Run: push the integrated `main` branch and run `Build Windows EXE`.

Expected: the dependency check reports `PyMuPDF 1.27.2.3`, the packaged bundle verification exits with code 0, and the EXE artifact uploads.

### Task 6: Record packaged verification errors without changing the GUI bootloader

**Files:**
- Modify: `tests/test_bundle_verification.py`
- Modify: `tests/test_build_workflow.py`
- Modify: `app.py`
- Modify: `.github/workflows/build-windows-exe.yml`

- [x] **Step 1: Write failing error-reporting tests**

```python
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
            self.assertIn("RuntimeError: PyMuPDF verification failed", error_log.read_text())
```

```python
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
            self.assertIn("RuntimeError: PyMuPDF import failed", error_log.read_text())

    def test_main_preserves_verification_error_when_error_logging_fails(self):
        error = RuntimeError("PyMuPDF verification failed")

        with (
            patch.object(app, "verify_pymupdf_bundle", side_effect=error),
            patch.object(app.sys, "argv", ["app.py", "--verify-bundle"]),
            patch.object(app.traceback, "format_exc", side_effect=RuntimeError("Unable to write")),
        ):
            with self.assertRaisesRegex(RuntimeError, "PyMuPDF verification failed"):
                app.main()
```

```python
    def test_preserves_windowed_build_and_prints_bundle_error_log(self):
        self.assertIn("--windowed `", self.workflow)
        self.assertIn("autoocr-bundle-verification-error.log", self.workflow)
        self.assertIn("Get-Content $errorLog", self.workflow)
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m unittest tests.test_bundle_verification tests.test_build_workflow -v`

Expected: FAIL because the command does not write an error log and the workflow uses the temporary console bootloader experiment.

- [x] **Step 3: Restore the windowed bootloader and write failure diagnostics**

Define `BUNDLE_VERIFICATION_ERROR_LOG = "autoocr-bundle-verification-error.log"` before importing runtime dependencies. Load Tkinter, PyMuPDF, Tesseract, Pillow and pypdf through one guarded loader. On a mandatory import error while `--verify-bundle` is requested, and on an exception from `verify_pymupdf_bundle()`, best-effort write `traceback.format_exc()` to that file and re-raise the original error. Restore `--windowed` in the production build and print the log in PowerShell before throwing the workflow failure.

- [x] **Step 4: Re-run focused tests**

Run: `venv/bin/python -m unittest tests.test_bundle_verification tests.test_build_workflow -v`

Expected: PASS.

- [ ] **Step 5: Validate the diagnostic run on Windows**

Run: push the updated `main` branch and run `Build Windows EXE`.

Expected: either the packaged verification succeeds, or the workflow prints the exact Python traceback needed for the next root-cause fix while preserving the user-facing windowed EXE.

### Task 7: Capture failures before the application module starts

**Files:**
- Create: `runtime_hooks/bundle_verification_diagnostics.py`
- Create: `tests/test_runtime_bundle_diagnostics.py`
- Modify: `tests/test_build_workflow.py`
- Modify: `.github/workflows/build-windows-exe.yml`

- [x] **Step 1: Write failing runtime-hook and workflow contract tests**

Cover both `--verify-bundle` stream redirection and the requirement that the Windows build include the hook while staying `--windowed`.

- [x] **Step 2: Run the tests to verify they fail**

Run: `venv/bin/python -m unittest tests.test_runtime_bundle_diagnostics tests.test_build_workflow -v`

Expected: FAIL because no runtime hook exists and the build does not reference it.

- [x] **Step 3: Add the conditional runtime hook and include it in PyInstaller**

The hook must only replace standard streams when `--verify-bundle` is present, writing to `autoocr-bundle-verification-error.log`. Add its source directory to the workflow path filter so edits trigger a new Windows build.

- [x] **Step 4: Re-run focused tests and build a local frozen executable**

Run: `venv/bin/python -m unittest tests.test_runtime_bundle_diagnostics tests.test_build_workflow -v`

Expected: PASS, and local PyInstaller output reports that it included the custom runtime hook.

- [ ] **Step 5: Validate the early-error diagnostic on Windows**

Run: push the updated `main` branch and run `Build Windows EXE`.

Expected: either `Verify packaged EXE` succeeds, or its log includes the exception emitted before `app.py` can write diagnostics.
