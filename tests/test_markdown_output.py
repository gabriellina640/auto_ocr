import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class FakePage:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class FakeReader:
    def __init__(self, _path):
        self.pages = [
            FakePage("Primeira linha\n\n\nSegunda linha  \n"),
            FakePage(""),
            FakePage("Texto da terceira pagina"),
        ]


class EmptyReader:
    def __init__(self, _path):
        self.pages = [FakePage(""), FakePage(None)]


class FallbackReader:
    def __init__(self, _path):
        self.pages = [
            FakePage(""),
            FakePage("Texto curto"),
        ]


class FakeFitzPage:
    def __init__(self, text):
        self.text = text

    def get_text(self, _mode):
        return self.text


class FakeFitzDocument:
    def __init__(self, pages):
        self.pages = pages
        self.page_count = len(pages)
        self.closed = False

    def __getitem__(self, index):
        return self.pages[index]

    def close(self):
        self.closed = True


def unavailable_fitz_open(*_args, **_kwargs):
    raise RuntimeError("PyMuPDF indisponivel no teste")


class MarkdownOutputTests(unittest.TestCase):
    def test_make_ocr_image_path_always_uses_png(self):
        self.assertEqual(app.make_ocr_image_path(Path("page_00001")).suffix, ".png")

    def test_prepare_ocr_image_keeps_dimensions_and_sets_dpi(self):
        image = app.Image.new("RGB", (100, 50), "white")
        prepared = app.prepare_ocr_image(image, dpi=300)

        self.assertEqual(prepared.size, (100, 50))
        self.assertEqual(prepared.mode, "RGB")
        self.assertEqual(prepared.info["dpi"], (300, 300))

    def test_markdown_output_path_matches_pdf_stem(self):
        self.assertEqual(
            app.markdown_output_path_for_pdf(Path("/tmp/processo_OCR.pdf")),
            Path("/tmp/processo_OCR.md"),
        )

    def test_safe_output_path_uses_timestamp_when_markdown_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "processo_OCR.md").write_text("antigo", encoding="utf-8")

            with patch.object(app, "app_base_dir", return_value=output_dir):
                output = app.safe_output_path(Path("/entrada/processo.pdf"))

            self.assertNotEqual(output, output_dir / "processo_OCR.pdf")
            self.assertTrue(output.name.startswith("processo_OCR_"))
            self.assertEqual(output.suffix, ".pdf")

    def test_normalize_markdown_text_removes_excess_spacing_and_unusual_breaks(self):
        text = "  Linha   com\t espacos\xa0extras  \u2028\u2029\n\n\nOutra   linha\fFinal  "

        normalized = app.normalize_markdown_text(text)

        self.assertEqual(normalized, "Linha com espacos extras\n\nOutra linha\nFinal")

    def test_markdown_from_pdf_text_adds_title_and_page_sections(self):
        with (
            patch.object(app, "PdfReader", FakeReader),
            patch.object(app.fitz, "open", side_effect=unavailable_fitz_open),
        ):
            markdown = app.markdown_from_pdf_text(Path("processo_OCR.pdf"))

        self.assertIn("# processo_OCR", markdown)
        self.assertIn("## Pagina 1", markdown)
        self.assertIn("Primeira linha\n\nSegunda linha", markdown)
        self.assertIn("## Pagina 2", markdown)
        self.assertIn("_Sem texto extraivel nesta pagina._", markdown)
        self.assertIn("## Pagina 3", markdown)
        self.assertTrue(markdown.endswith("\n"))

    def test_markdown_from_pdf_text_uses_pymupdf_when_it_extracts_more_text(self):
        fitz_document = FakeFitzDocument([
            FakeFitzPage("Texto recuperado pelo PyMuPDF"),
            FakeFitzPage("Texto curto com complemento extra"),
        ])

        with (
            patch.object(app, "PdfReader", FallbackReader),
            patch.object(app.fitz, "open", return_value=fitz_document),
        ):
            markdown = app.markdown_from_pdf_text(Path("processo_OCR.pdf"))

        self.assertIn("Texto recuperado pelo PyMuPDF", markdown)
        self.assertIn("Texto curto com complemento extra", markdown)
        self.assertNotIn("_Sem texto extraivel nesta pagina._", markdown)
        self.assertTrue(fitz_document.closed)

    def test_markdown_from_pdf_text_rejects_pdf_without_text(self):
        with (
            patch.object(app, "PdfReader", EmptyReader),
            patch.object(app.fitz, "open", side_effect=unavailable_fitz_open),
        ):
            with self.assertRaisesRegex(RuntimeError, "texto extraivel"):
                app.markdown_from_pdf_text(Path("vazio.pdf"))

    def test_write_markdown_from_pdf_creates_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "saida.md"

            with (
                patch.object(app, "PdfReader", FakeReader),
                patch.object(app.fitz, "open", side_effect=unavailable_fitz_open),
            ):
                result = app.write_markdown_from_pdf(Path("entrada.pdf"), output)

            self.assertEqual(result, output)
            self.assertIn("Texto da terceira pagina", output.read_text(encoding="utf-8"))

    def test_write_markdown_from_pdf_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "saida.md"
            output.write_text("conteudo antigo", encoding="utf-8")

            with patch.object(app, "PdfReader", FakeReader):
                with self.assertRaises(FileExistsError):
                    app.write_markdown_from_pdf(Path("entrada.pdf"), output)

            self.assertEqual(output.read_text(encoding="utf-8"), "conteudo antigo")


if __name__ == "__main__":
    unittest.main()
