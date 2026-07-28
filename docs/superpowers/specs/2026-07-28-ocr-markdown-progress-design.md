# OCR Markdown and Progress Design

## Goal

Improve the Auto OCR PDF desktop flow by making progress status more visible, opening the app maximized, removing the PDF compression option, and generating a lightweight Markdown file automatically after the searchable PDF is validated.

## Scope

- Open the Tkinter window maximized/full-screen-like by default, with a safe geometry fallback when platform-specific maximize calls fail.
- Replace the subtle progress area with a stronger visual block: large percentage text, thicker progress bar, and clear current step text.
- Remove the user-facing compression choice and remove the alternate compressed OCR profile from the processing flow.
- Generate a Markdown file automatically from the validated searchable PDF, with a section for every PDF page.
- Add a result action for opening the generated Markdown file.
- Keep the searchable PDF as the primary validated visual output.

## Out Of Scope

- Replacing the PDF output with Markdown only.
- Rebuilding the UI framework.
- Adding manual Markdown options or format settings.
- Preserving the old reduced-size compression mode.

## Architecture

The OCR pipeline remains centered on `run_compatibility_mode`: render each input page, run Tesseract, assemble the searchable PDF, validate the temporary PDF, generate a temporary Markdown file, then publish both final files together.

The UI keeps the existing Tkinter structure but replaces the compression card with a Markdown information card. Processing state now tracks both `output_pdf` and `output_markdown`, and result actions expose both artifacts.

## Data Flow

1. User selects or drops a PDF.
2. App renders and OCRs each page.
3. App validates the temporary OCR PDF.
4. App extracts searchable text from that PDF into a temporary Markdown file.
5. App publishes `*_OCR.pdf` and `*_OCR.md` together.
6. App enables actions to open PDF, Markdown, and folder.

## Error Handling

- If PDF OCR or validation fails, no final output is released.
- If Markdown generation fails, the process is reported as failed and final PDF/Markdown files are not published.
- If a Markdown page has no extractable text, the Markdown still includes that page with a clear empty-page marker.
- If either final output name already exists, the app chooses a timestamped output path before processing starts.
- If the app cannot maximize through platform APIs, it falls back to screen-sized geometry and continues.

## Testing

- Unit tests cover Markdown output path generation and Markdown formatting from extracted page text.
- Existing compression-profile tests are replaced because compression is removed from the public flow.
- Existing temp-management tests remain.
- Validation command: `venv/bin/python -m unittest discover -s tests -v`.
