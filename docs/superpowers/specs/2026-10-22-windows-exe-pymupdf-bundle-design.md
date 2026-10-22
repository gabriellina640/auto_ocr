# Windows EXE PyMuPDF Bundle Design

**Date:** 2026-10-22

## Context

The Windows one-file executable fails while importing PyMuPDF from the PyInstaller temporary `_MEI...` directory. The build currently collects the drag-and-drop package and Tesseract files, but does not explicitly collect the native files distributed with the `pymupdf` package.

## Decision

Keep the `main` branch feature set unchanged and update only the Windows packaging path.

- Import PyMuPDF through its current package name with `import pymupdf as fitz`.
- Use PyInstaller's `--collect-all pymupdf` option to bundle PyMuPDF submodules, data and native binaries.
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

- Run the focused unit tests before and after implementation.
- Run the complete existing unit test suite.
- Run Python bytecode compilation for modified Python files.
- Let GitHub Actions build and run the generated Windows executable before uploading it.
