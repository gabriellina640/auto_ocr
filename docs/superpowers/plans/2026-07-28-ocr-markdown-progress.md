# OCR Markdown and Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make progress more visible, open the app maximized, remove compression controls, and generate Markdown automatically after OCR.

**Architecture:** Keep the existing Tkinter app and OCR pipeline in `app.py`. Replace compression state with Markdown artifact state, generate Markdown from the validated OCR PDF, and update focused unit tests.

**Tech Stack:** Python, Tkinter, PyMuPDF, pypdf, pytesseract, Pillow, unittest.

---

### Task 1: Markdown Helpers

**Files:**
- Modify: `app.py`
- Delete: `tests/test_compression_profiles.py`
- Create: `tests/test_markdown_output.py`

- [x] Add `markdown_output_path_for_pdf(output_pdf: Path) -> Path`.
- [x] Add `markdown_from_pdf_text(pdf_path: Path) -> str` using `PdfReader.extract_text()`.
- [x] Add `write_markdown_from_pdf(pdf_path: Path, markdown_path: Path) -> Path`.
- [x] Replace compression profile tests with Markdown helper tests.
- [x] Run `venv/bin/python -m unittest discover -s tests -v`.

### Task 2: Pipeline Integration

**Files:**
- Modify: `app.py`

- [x] Remove `CompressionProfile`, `COMPRESSION_PROFILES`, compression toggle state, and compressed image behavior.
- [x] Keep OCR image generation in faithful PNG mode at `DEFAULT_DPI`.
- [x] After `run_compatibility_mode` returns a validated report, generate `*_OCR.md` from the published OCR PDF.
- [x] Treat Markdown generation failure as processing failure.
- [x] Run `venv/bin/python -m unittest discover -s tests -v`.

### Task 3: UI Updates

**Files:**
- Modify: `app.py`

- [x] Add maximized startup helper and call it during app initialization.
- [x] Replace compression card with Markdown card.
- [x] Make progress area visually stronger with large percentage, visible current step, and thicker progress bar.
- [x] Add an "Abrir Markdown" result button.
- [x] Update button enable/disable behavior for Markdown output.
- [x] Run `venv/bin/python -m unittest discover -s tests -v`.

### Task 4: Docs and Final Validation

**Files:**
- Modify: `README.md`

- [x] Update README to describe automatic Markdown output instead of optional compression.
- [x] Run `venv/bin/python -m unittest discover -s tests -v`.
- [x] Review `git diff -- app.py README.md tests/test_markdown_output.py .github/workflows/build-windows-exe.yml`.
