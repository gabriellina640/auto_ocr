# Windows EXE PyMuPDF Bundle Design

**Date:** 2026-10-22

## Context

The Windows one-file executable fails while importing PyMuPDF from the PyInstaller temporary `_MEI...` directory. The build currently collects the drag-and-drop package and Tesseract files, but does not explicitly collect the native files distributed with the `pymupdf` package.

The first packaging verification exposed a second dependency regression. Because `requirements.txt` allowed any PyMuPDF release, the Windows runner installed PyMuPDF 2.0 and its `pymupdf-layout` dependency. The generated executable then failed during import because the unused layout package expected `pymupdf/layout/resources/onnx/layout_rtf2.4.1+imf1.yaml` inside the one-file bundle. The application only uses PyMuPDF document APIs and has no layout-analysis feature.

After pinning the dependency, the Windows build, dependency check and OCR smoke tests passed, but the packaged executable still returned exit code 1. Its `--windowed` bootloader suppressed the traceback in the non-interactive runner. PyInstaller documents that windowed Windows executables have no standard input, output or error streams. That both prevents diagnosis and can break libraries that use those streams.

## Decision

Keep the `main` branch feature set unchanged and update only the Windows packaging path.

- Import PyMuPDF through its current package name with `import pymupdf as fitz`.
- Use PyInstaller's `--collect-all pymupdf` option to bundle PyMuPDF submodules, data and native binaries.
- Pin PyMuPDF to `1.27.2.3`, the version already used by the project and without the unneeded PyMuPDF Layout dependency.
- Verify in the Windows workflow that the exact pinned version is installed and that `pymupdf.layout` is absent before building the executable.
- Preserve the `--windowed` bootloader so ordinary launches retain the existing no-console UX.
- When importing any mandatory runtime dependency or running `--verify-bundle` fails, best-effort write its Python traceback to `autoocr-bundle-verification-error.log`; the workflow prints that file before failing the job without replacing the original exception.
- Add a PyInstaller runtime hook that redirects standard error to that same file only for `--verify-bundle`. Runtime hooks run before `app.py`, so errors that prevent the application module from loading are also observable without changing the production executable from `--windowed`.
- Add a headless `--verify-bundle` command that creates and serializes an in-memory PDF. It exits before Tkinter starts.
- Run the command against `dist\\AutoOCRPDF.exe` after PyInstaller completes in GitHub Actions. A failed import or missing library will fail the workflow and prevent artifact upload.

## Scope

Included:

- `app.py` import and headless bundle verification path.
- Unit tests for the verification path and no-GUI command dispatch.
- Windows workflow collection and executable smoke verification.

Excluded:

- OCR, compression, UI, Tesseract and output naming behavior.
- The Markdown changes from `versao/drocimar`.

## Validation

The Windows verification must use `Start-Process -Wait -PassThru` and inspect the returned process `ExitCode`. Direct invocation of the windowed executable can return before completion and leave `$LASTEXITCODE` unset, producing a false workflow failure. The verification step has a three-minute timeout.

- Run the focused unit tests before and after implementation.
- Run the complete existing unit test suite.
- Run Python bytecode compilation for modified Python files.
- Let GitHub Actions build and run the generated Windows executable before uploading it.
- Confirm the workflow reports PyMuPDF `1.27.2.3` without `pymupdf.layout`.
