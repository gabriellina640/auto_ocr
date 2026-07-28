import os
import sys
import shutil
import queue
import tempfile
import threading
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from pypdf import PdfWriter, PdfReader

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    DND_FILES = None
    TkinterDnD = None

windnd = None
if os.name == "nt":
    try:
        import windnd
    except Exception:
        windnd = None

DND_ERROR = ""


APP_NAME = "Auto OCR PDF"
APP_VERSION = "1.2.0"
DEFAULT_LANGUAGE = "por"
DEFAULT_DPI = 300
PAGE_SIZE_TOLERANCE = 2.0

COLOR_BG = "#f5f6f8"
COLOR_CARD = "#ffffff"
COLOR_CARD_ALT = "#edeff2"
COLOR_BRAND_SOFT = "#fbeaec"
COLOR_BORDER = "#e3e6ea"
COLOR_PRIMARY = "#a5122a"
COLOR_PRIMARY_DARK = "#7e0e20"
COLOR_SECONDARY = "#ffffff"
COLOR_SECONDARY_DARK = "#edeff2"
COLOR_SUCCESS = "#1e7137"
COLOR_SUCCESS_BG = "#dff5e3"
COLOR_WARNING = "#865700"
COLOR_WARNING_BG = "#fdeccb"
COLOR_TEXT = "#1a1a1a"
COLOR_TEXT_DARK = "#101114"
COLOR_MUTED = "#666b73"
COLOR_LOG_BG = "#ffffff"
COLOR_LOG_TEXT = "#3d3d3d"
COLOR_DISABLED_BG = "#edeff2"
COLOR_DISABLED_TEXT = "#555c64"
COLOR_ON_PRIMARY = "#ffffff"
FONT_SANS = "Inter"
FONT_FALLBACK = "Segoe UI"

SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32


def ui_font(size: int, weight: str | None = None) -> tuple:
    try:
        family = FONT_SANS if FONT_SANS in tkfont.families() else FONT_FALLBACK
    except tk.TclError:
        family = FONT_FALLBACK

    if weight:
        return (family, size, weight)
    return (family, size)


@dataclass(frozen=True)
class PdfValidationReport:
    pages: int
    pages_with_text: int
    warnings: list[str]


class ProcessingCancelled(Exception):
    pass


# ============================================================
# UTILITARIOS
# ============================================================

def is_windows() -> bool:
    return os.name == "nt"


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def create_root_window() -> tk.Tk:
    global DND_FILES, TkinterDnD, DND_ERROR

    if TkinterDnD is not None:
        try:
            return TkinterDnD.Tk()
        except Exception as e:
            DND_ERROR = str(e)
            DND_FILES = None
            TkinterDnD = None

    return tk.Tk()


def hidden_subprocess_kwargs() -> dict:
    if not is_windows():
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0

    kwargs = {"startupinfo": startupinfo}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def app_base_dir() -> Path:
    if is_frozen_app():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_base_dir() -> Path:
    if is_frozen_app() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return app_base_dir()


def bundled_resource(*parts: str) -> Path:
    return resource_base_dir().joinpath(*parts)


def open_file(path: Path):
    try:
        if is_windows():
            os.startfile(path)
        else:
            messagebox.showwarning("Atencao", "Abrir arquivo e suportado no EXE Windows.")
    except Exception as e:
        messagebox.showerror("Erro", f"Nao foi possivel abrir o arquivo:\n\n{e}")


def open_folder(path: Path):
    try:
        folder = path if path.is_dir() else path.parent

        if is_windows():
            os.startfile(folder)
        else:
            messagebox.showwarning("Atencao", "Abrir pasta e suportado no EXE Windows.")
    except Exception as e:
        messagebox.showerror("Erro", f"Nao foi possivel abrir a pasta:\n\n{e}")


def safe_output_path(input_pdf: Path) -> Path:
    output_dir = app_base_dir()
    base = output_dir / f"{input_pdf.stem}_OCR.pdf"

    if not base.exists() and not base.with_suffix(".md").exists():
        return base

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"{input_pdf.stem}_OCR_{timestamp}.pdf"


def split_languages(language: str) -> list[str]:
    return [item.strip() for item in language.split("+") if item.strip()]


def bundled_tesseract_candidates() -> list[Path]:
    if is_windows():
        names = ["tesseract.exe"]
    else:
        names = ["tesseract"]

    candidates: list[Path] = []
    for name in names:
        candidates.append(bundled_resource("vendor", "tesseract", name))
        candidates.append(app_base_dir() / "vendor" / "tesseract" / name)
    return candidates


def configure_tessdata_prefix() -> Path | None:
    candidates = [
        bundled_resource("vendor", "tessdata"),
        app_base_dir() / "vendor" / "tessdata",
    ]

    for candidate in candidates:
        if candidate.exists():
            os.environ["TESSDATA_PREFIX"] = str(candidate)
            return candidate

    return None


def check_tesseract(language: str = "por") -> tuple[bool, str]:
    """
    Procura o Tesseract no pacote do EXE, no PATH e em caminhos comuns.
    Tambem valida os idiomas solicitados para evitar falha no meio do OCR.
    """
    configure_tessdata_prefix()

    possible_paths: list[str] = []
    env_path = os.environ.get("TESSERACT_CMD", "").strip()
    if env_path:
        possible_paths.append(env_path)

    possible_paths.extend(str(path) for path in bundled_tesseract_candidates())
    possible_paths.extend([
        "tesseract",
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ])

    requested_langs = split_languages(language)
    if not requested_langs:
        requested_langs = ["por"]

    checked: set[str] = set()
    for path in possible_paths:
        if path in checked:
            continue
        checked.add(path)

        try:
            if path != "tesseract" and not Path(path).exists():
                continue

            pytesseract.pytesseract.tesseract_cmd = path
            version = pytesseract.get_tesseract_version()

            try:
                langs = pytesseract.get_languages(config="")
            except Exception:
                langs = []

            missing = [lang for lang in requested_langs if lang not in langs]
            if missing:
                return False, (
                    f"Tesseract encontrado em:\n{path}\n\n"
                    f"Versao:\n{version}\n\n"
                    "Mas faltam idiomas do OCR:\n"
                    f"{', '.join(missing)}\n\n"
                    "Gere o EXE pelo GitHub Actions para embutir o idioma portugues "
                    "automaticamente no pacote final."
                )

            tessdata = os.environ.get("TESSDATA_PREFIX", "padrao do Tesseract")
            return True, (
                f"Tesseract OK: {path} | versao {version} | "
                f"idiomas: {'+'.join(requested_langs)} | tessdata: {tessdata}"
            )

        except Exception:
            continue

    return False, (
        "Tesseract OCR nao foi encontrado.\n\n"
        "Gere o EXE pelo GitHub Actions para embutir o Tesseract e o idioma "
        "portugues automaticamente no pacote final."
    )


def pil_image_from_pixmap(pix: fitz.Pixmap, dpi: int) -> Image.Image:
    if pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)

    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    image.info["dpi"] = (dpi, dpi)
    return image


def make_ocr_image_path(output_base: Path) -> Path:
    return output_base.with_suffix(".png")


def prepare_ocr_image(image: Image.Image, dpi: int = DEFAULT_DPI) -> Image.Image:
    prepared = image if image.mode == "RGB" else image.convert("RGB")
    prepared.info["dpi"] = (dpi, dpi)
    return prepared


def save_ocr_image(image: Image.Image, image_path: Path, dpi: int):
    image.save(image_path, format="PNG", dpi=(dpi, dpi))


def raise_if_cancelled(cancel_event: threading.Event | None):
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessingCancelled("Processamento cancelado pelo usuario.")


def run_tesseract_pdf(
    image: Image.Image,
    output_base: Path,
    language: str,
    dpi: int,
    cancel_event: threading.Event | None = None,
) -> Path:
    raise_if_cancelled(cancel_event)

    image = prepare_ocr_image(image, dpi=dpi)
    image_path = make_ocr_image_path(output_base)
    output_pdf = output_base.with_suffix(".pdf")

    save_ocr_image(image, image_path, dpi)

    command = [
        pytesseract.pytesseract.tesseract_cmd or "tesseract",
        str(image_path),
        str(output_base),
        "-l",
        language,
        "--psm",
        "3",
        "-c",
        "preserve_interword_spaces=1",
        "pdf",
    ]

    env = os.environ.copy()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        **hidden_subprocess_kwargs(),
    )

    while process.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            output_pdf.unlink(missing_ok=True)
            raise ProcessingCancelled("Processamento cancelado pelo usuario.")

        try:
            process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            pass

    stdout_bytes, stderr_bytes = process.communicate()
    stderr = stderr_bytes.decode(errors="replace").strip()
    stdout = stdout_bytes.decode(errors="replace").strip()

    cli_detail = stderr or stdout or "sem detalhe tecnico"
    if output_pdf.exists() and output_pdf.stat().st_size > 0:
        try:
            PdfReader(str(output_pdf))
            return output_pdf
        except Exception as e:
            cli_detail = f"PDF OCR gerado pelo CLI estava invalido: {e}. {cli_detail}"
            output_pdf.unlink(missing_ok=True)

    try:
        raise_if_cancelled(cancel_event)
        pdf_bytes = pytesseract.image_to_pdf_or_hocr(
            image,
            extension="pdf",
            lang=language,
            config="--psm 3 -c preserve_interword_spaces=1",
        )
        raise_if_cancelled(cancel_event)
        output_pdf.write_bytes(pdf_bytes)
        PdfReader(str(output_pdf))
        return output_pdf
    except Exception as e:
        output_pdf.unlink(missing_ok=True)
        if isinstance(e, ProcessingCancelled):
            raise
        if process.returncode != 0:
            raise RuntimeError(
                "Tesseract nao conseguiu gerar PDF OCR. "
                f"CLI: {cli_detail}. Fallback pytesseract: {e}"
            ) from e
        raise RuntimeError(
            "Tesseract terminou sem gerar um PDF OCR valido. "
            f"CLI: {cli_detail}. Fallback pytesseract: {e}"
        ) from e


def make_temp_output_path(output_pdf: Path) -> Path:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{output_pdf.stem}_",
        suffix=".tmp.pdf",
        dir=str(output_pdf.parent),
    )
    os.close(fd)
    return Path(name)


def make_temp_markdown_path(output_markdown: Path) -> Path:
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{output_markdown.stem}_",
        suffix=".tmp.md",
        dir=str(output_markdown.parent),
    )
    os.close(fd)
    Path(name).unlink(missing_ok=True)
    return Path(name)


def make_page_temp_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="auto_ocr_pages_"))


def cleanup_temp_tree(
    temp_dir: Path,
    progress_callback,
    attempts: int = 5,
    delay_seconds: float = 0.2,
) -> bool:
    if not temp_dir.exists():
        return True

    for attempt in range(1, attempts + 1):
        try:
            shutil.rmtree(temp_dir)
            return True
        except FileNotFoundError:
            return True
        except OSError as e:
            if attempt == attempts:
                progress_callback(
                    "Aviso: nao foi possivel remover a pasta temporaria "
                    f"{temp_dir}: {e}"
                )
                return False
            time.sleep(delay_seconds)

    return False


def validate_pdf_output(input_pdf: Path, output_pdf: Path) -> PdfValidationReport:
    warnings: list[str] = []

    if not output_pdf.exists() or output_pdf.stat().st_size == 0:
        raise RuntimeError("O PDF final nao foi criado corretamente.")

    try:
        source = fitz.open(str(input_pdf))
        result = fitz.open(str(output_pdf))
    except Exception as e:
        raise RuntimeError(f"O PDF final nao pode ser aberto para validacao: {e}") from e

    try:
        if source.page_count != result.page_count:
            raise RuntimeError(
                "Validacao falhou: a quantidade de paginas mudou "
                f"({source.page_count} entrada, {result.page_count} saida)."
            )

        for index in range(source.page_count):
            source_rect = source[index].rect
            result_rect = result[index].rect
            width_delta = abs(source_rect.width - result_rect.width)
            height_delta = abs(source_rect.height - result_rect.height)
            if width_delta > PAGE_SIZE_TOLERANCE or height_delta > PAGE_SIZE_TOLERANCE:
                warnings.append(
                    "Pagina "
                    f"{index + 1}: tamanho diferente "
                    f"({source_rect.width:.1f}x{source_rect.height:.1f} -> "
                    f"{result_rect.width:.1f}x{result_rect.height:.1f})."
                )
    finally:
        source.close()
        result.close()

    try:
        reader = PdfReader(str(output_pdf))
        pages_with_text = sum(1 for page in reader.pages if (page.extract_text() or "").strip())
    except Exception as e:
        raise RuntimeError(f"O PDF final foi criado, mas a camada de texto nao pode ser validada: {e}") from e

    if pages_with_text == 0:
        raise RuntimeError(
            "Validacao falhou: o PDF final nao possui texto pesquisavel extraivel."
        )

    return PdfValidationReport(
        pages=len(reader.pages),
        pages_with_text=pages_with_text,
        warnings=warnings,
    )


def publish_validated_outputs(
    temp_pdf: Path,
    output_pdf: Path,
    temp_markdown: Path,
    output_markdown: Path,
):
    if output_pdf.exists() or output_markdown.exists():
        raise RuntimeError(
            "Nao foi possivel publicar os arquivos finais porque o destino ja existe."
        )

    os.replace(temp_pdf, output_pdf)
    try:
        os.replace(temp_markdown, output_markdown)
    except Exception:
        output_pdf.unlink(missing_ok=True)
        raise


def markdown_output_path_for_pdf(output_pdf: Path) -> Path:
    return output_pdf.with_suffix(".md")


def normalize_markdown_text(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized: list[str] = []
    previous_blank = False

    for line in lines:
        clean = line.rstrip()
        is_blank = not clean.strip()
        if is_blank and previous_blank:
            continue
        normalized.append(clean)
        previous_blank = is_blank

    return "\n".join(normalized).strip()


def markdown_from_pdf_text(pdf_path: Path) -> str:
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as e:
        raise RuntimeError(f"Nao foi possivel abrir o PDF OCR para gerar Markdown: {e}") from e

    sections = [f"# {pdf_path.stem}", ""]
    pages_with_text = 0

    for index, page in enumerate(reader.pages, start=1):
        text = normalize_markdown_text(page.extract_text() or "")
        if text:
            pages_with_text += 1
        else:
            text = "_Sem texto extraivel nesta pagina._"

        sections.extend([f"## Pagina {index}", "", text, ""])

    if pages_with_text == 0:
        raise RuntimeError("Nao foi encontrado texto extraivel para gerar o Markdown.")

    return "\n".join(sections).strip() + "\n"


def write_markdown_from_pdf(pdf_path: Path, markdown_path: Path) -> Path:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    with open(markdown_path, "x", encoding="utf-8") as markdown_file:
        markdown_file.write(markdown_from_pdf_text(pdf_path))
    return markdown_path


# ============================================================
# PROCESSAMENTO OCR
# ============================================================

def run_compatibility_mode(
    input_pdf: Path,
    output_pdf: Path,
    output_markdown: Path,
    language: str,
    dpi: int,
    progress_callback,
    progress_percent_callback,
    cancel_event: threading.Event | None = None,
) -> PdfValidationReport:
    """
    Modo compatibilidade:
    Renderiza cada pagina como imagem e aplica OCR.
    Preserva pagina, proporcao e dimensao fisica para reduzir risco visual.
    """
    raise_if_cancelled(cancel_event)
    progress_callback("Abrindo PDF...")

    document = fitz.open(str(input_pdf))
    total_pages = document.page_count

    if total_pages == 0:
        document.close()
        raise RuntimeError("O PDF nao possui paginas.")

    writer = PdfWriter()
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    temp_dir = make_page_temp_dir()
    temp_output = make_temp_output_path(output_pdf)
    temp_markdown = make_temp_markdown_path(output_markdown)

    try:
        for page_index in range(total_pages):
            raise_if_cancelled(cancel_event)
            page_number = page_index + 1

            progress_callback(f"Renderizando pagina {page_number} de {total_pages}...")
            source_page = document.load_page(page_index)
            source_rect = source_page.rect
            pix = source_page.get_pixmap(matrix=matrix, alpha=False)
            image = pil_image_from_pixmap(pix, dpi)

            progress_callback(f"Aplicando OCR na pagina {page_number} de {total_pages}...")
            temp_page_base = temp_dir / f"page_{page_number:05d}"
            temp_page_pdf = run_tesseract_pdf(
                image=image,
                output_base=temp_page_base,
                language=language,
                dpi=dpi,
                cancel_event=cancel_event,
            )

            raise_if_cancelled(cancel_event)
            reader = PdfReader(str(temp_page_pdf))
            ocr_page = reader.pages[0]
            ocr_page.scale_to(float(source_rect.width), float(source_rect.height))
            writer.add_page(ocr_page)

            percent = int((page_number / total_pages) * 90)
            progress_percent_callback(percent)

        raise_if_cancelled(cancel_event)
        progress_callback("Salvando PDF temporario...")
        with open(temp_output, "wb") as f:
            writer.write(f)

        raise_if_cancelled(cancel_event)
        progress_percent_callback(95)
        progress_callback("Validando PDF final...")
        report = validate_pdf_output(input_pdf, temp_output)

        raise_if_cancelled(cancel_event)
        progress_percent_callback(97)
        progress_callback("Gerando Markdown final...")
        write_markdown_from_pdf(temp_output, temp_markdown)

        raise_if_cancelled(cancel_event)
        progress_percent_callback(99)
        progress_callback("Publicando arquivos finais...")
        publish_validated_outputs(temp_output, output_pdf, temp_markdown, output_markdown)
        progress_percent_callback(100)
        progress_callback("PDF OCR e Markdown criados com sucesso.")
        return report

    finally:
        document.close()
        cleanup_temp_tree(temp_dir, progress_callback)
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)
        if temp_markdown.exists():
            temp_markdown.unlink(missing_ok=True)


# ============================================================
# INTERFACE
# ============================================================

class ActionButton(tk.Frame):
    def __init__(self, parent, text: str, command, primary: bool = False):
        border_color = COLOR_PRIMARY if primary else COLOR_BORDER
        super().__init__(parent, bd=0, highlightthickness=1, highlightbackground=border_color)
        self.command = command
        self.primary = primary
        self.state = "normal"
        self.text = text

        self.normal_bg = COLOR_PRIMARY if primary else COLOR_SECONDARY
        self.active_bg = COLOR_PRIMARY_DARK if primary else COLOR_SECONDARY_DARK
        self.disabled_bg = COLOR_DISABLED_BG
        self.normal_fg = COLOR_ON_PRIMARY if primary else COLOR_TEXT
        self.disabled_fg = COLOR_DISABLED_TEXT

        self.label = tk.Label(
            self,
            text=text,
            font=ui_font(10, "bold"),
            padx=SPACE_5,
            pady=SPACE_4,
            width=28,
            anchor="center",
            cursor="hand2",
        )
        self.label.pack(fill="both", expand=True)

        self.bind("<Button-1>", self._click)
        self.label.bind("<Button-1>", self._click)
        self.bind("<Enter>", self._enter)
        self.label.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.label.bind("<Leave>", self._leave)

        self._paint(self.normal_bg)

    def _paint(self, bg: str):
        fg = self.disabled_fg if self.state == "disabled" else self.normal_fg
        self.configure(bg=bg)
        self.label.configure(bg=bg, fg=fg)

    def _click(self, _event=None):
        if self.state != "disabled":
            self.command()

    def _enter(self, _event=None):
        if self.state != "disabled":
            self._paint(self.active_bg)

    def _leave(self, _event=None):
        self._paint(self.disabled_bg if self.state == "disabled" else self.normal_bg)

    def config(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)

        if "text" in kwargs:
            self.text = kwargs.pop("text")
            self.label.configure(text=self.text)

        if "state" in kwargs:
            self.state = kwargs.pop("state")
            if self.state == "disabled":
                self.label.configure(cursor="arrow")
                self._paint(self.disabled_bg)
            else:
                self.label.configure(cursor="hand2")
                self._paint(self.normal_bg)

        if kwargs:
            super().config(**kwargs)

    configure = config

    def cget(self, key):
        if key == "text":
            return self.text
        if key == "state":
            return self.state
        return super().cget(key)


class AutoOCRApp:
    def __init__(self, root: tk.Tk):
        self.root = root

        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1360x900")
        self.root.minsize(1040, 740)
        self.root.configure(bg=COLOR_BG)
        self.maximize_root_window()

        self.selected_pdf: Path | None = None
        self.output_pdf: Path | None = None
        self.output_markdown: Path | None = None
        self.last_report: PdfValidationReport | None = None
        self.worker_thread: threading.Thread | None = None
        self.active_worker_threads: set[threading.Thread] = set()
        self.processing_busy = False
        self.upload_area: tk.Frame | None = None
        self.cancel_event = threading.Event()
        self.current_job_id = 0
        self.cancelled_job_ids: set[int] = set()
        self.closing = False
        self.after_ids: set[str] = set()

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.status_queue: queue.Queue[str] = queue.Queue()
        self.progress_queue: queue.Queue[int] = queue.Queue()

        self.root.protocol("WM_DELETE_WINDOW", self.close_app)
        self.setup_style()
        self.create_layout()
        self.configure_drag_and_drop()
        self.process_queues()

    # --------------------------------------------------------

    def maximize_root_window(self):
        try:
            self.root.state("zoomed")
            return
        except tk.TclError:
            pass

        try:
            self.root.attributes("-zoomed", True)
            return
        except tk.TclError:
            pass

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_width}x{screen_height}+0+0")

    # --------------------------------------------------------

    def after_ui(self, delay_ms: int, callback):
        if self.closing:
            return None

        holder: dict[str, str] = {}

        def wrapped_callback():
            after_id = holder.get("id")
            if after_id is not None:
                self.after_ids.discard(after_id)

            if self.closing:
                return

            callback()

        try:
            after_id = self.root.after(delay_ms, wrapped_callback)
            holder["id"] = after_id
            self.after_ids.add(after_id)
            return after_id
        except tk.TclError:
            return None

    # --------------------------------------------------------

    def close_app(self):
        if self.closing:
            return

        self.closing = True
        self.cancel_event.set()

        for after_id in list(self.after_ids):
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
            self.after_ids.discard(after_id)

        if self.has_active_workers():
            self.wait_for_workers_before_close()
            return

        self.destroy_root()

    # --------------------------------------------------------

    def has_active_workers(self) -> bool:
        self.active_worker_threads = {
            thread for thread in self.active_worker_threads if thread.is_alive()
        }
        return bool(self.active_worker_threads)

    # --------------------------------------------------------

    def wait_for_workers_before_close(self):
        if self.has_active_workers():
            try:
                self.root.after(50, self.wait_for_workers_before_close)
            except tk.TclError:
                pass
            return

        self.destroy_root()

    # --------------------------------------------------------

    def destroy_root(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

        try:
            self.root.quit()
        except tk.TclError:
            pass

    # --------------------------------------------------------

    def setup_style(self):
        style = ttk.Style()

        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            "TProgressbar",
            troughcolor=COLOR_CARD_ALT,
            background=COLOR_PRIMARY,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_PRIMARY,
            darkcolor=COLOR_PRIMARY,
            thickness=26,
        )

    # --------------------------------------------------------

    def make_card(self, parent, title: str | None = None, **pack_options) -> tk.Frame:
        card = tk.Frame(
            parent,
            bg=COLOR_CARD,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            bd=0,
        )
        card.pack(**pack_options)

        if title:
            header = tk.Frame(card, bg=COLOR_CARD)
            header.pack(fill="x", padx=SPACE_5, pady=(SPACE_5, SPACE_4))

            accent = tk.Frame(header, bg=COLOR_PRIMARY, width=4, height=24)
            accent.pack(side="left", padx=(0, SPACE_3))
            accent.pack_propagate(False)

            label = tk.Label(
                header,
                text=title,
                bg=COLOR_CARD,
                fg=COLOR_TEXT,
                font=ui_font(13, "bold"),
                anchor="w",
            )
            label.pack(side="left", fill="x", expand=True)

        return card

    # --------------------------------------------------------

    def make_action_button(self, parent, text: str, command, primary: bool = False) -> ActionButton:
        return ActionButton(parent, text=text, command=command, primary=primary)

    # --------------------------------------------------------

    def create_layout(self):
        main = tk.Frame(self.root, bg=COLOR_BG)
        main.pack(fill="both", expand=True, padx=SPACE_6, pady=SPACE_6)

        header = tk.Frame(main, bg=COLOR_BG)
        header.pack(fill="x")

        accent_line = tk.Frame(header, bg=COLOR_PRIMARY, height=4, width=72)
        accent_line.pack(anchor="w", pady=(0, 12))
        accent_line.pack_propagate(False)

        kicker = tk.Label(
            header,
            text="MPAC | SAJ OCR",
            bg=COLOR_BG,
            fg=COLOR_PRIMARY,
            font=ui_font(9, "bold"),
        )
        kicker.pack(anchor="w", pady=(0, 6))

        title = tk.Label(
            header,
            text="Auto OCR PDF",
            bg=COLOR_BG,
            fg=COLOR_TEXT_DARK,
            font=ui_font(30, "bold"),
            anchor="w",
        )
        title.pack(anchor="w")

        subtitle = tk.Label(
            header,
            text="Selecione o PDF do SAJ. O app gera uma copia pesquisavel e um Markdown leve automaticamente.",
            bg=COLOR_BG,
            fg=COLOR_MUTED,
            font=ui_font(10),
            anchor="w",
            wraplength=900,
            justify="left",
        )
        subtitle.pack(anchor="w", pady=(4, 0))

        content = tk.Frame(main, bg=COLOR_BG)
        content.pack(fill="both", expand=True, pady=(SPACE_5, 0))
        content.grid_columnconfigure(0, weight=3, minsize=560)
        content.grid_columnconfigure(1, weight=1, minsize=320)
        content.grid_rowconfigure(0, weight=1)

        left = tk.Frame(content, bg=COLOR_BG)
        left.grid(row=0, column=0, sticky="nsew")

        right = tk.Frame(content, bg=COLOR_BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(SPACE_5, 0))

        self.create_file_card(left)
        self.create_markdown_card(left)
        self.create_progress_card(left)
        self.create_log_card(left)

        self.create_validation_card(right)
        self.create_actions_card(right)
        self.create_help_card(right)

    # --------------------------------------------------------

    def create_file_card(self, parent):
        card = self.make_card(parent, "Entrada", fill="x")

        upload_area = tk.Frame(
            card,
            bg=COLOR_CARD,
            highlightbackground=COLOR_PRIMARY,
            highlightthickness=2,
            height=230,
        )
        self.upload_area = upload_area
        upload_area.pack(fill="x", padx=SPACE_5, pady=(0, SPACE_5))
        upload_area.pack_propagate(False)

        icon_row = tk.Frame(upload_area, bg=COLOR_CARD)
        icon_row.pack(pady=(SPACE_6, SPACE_3))

        icon = tk.Label(
            icon_row,
            text="PDF",
            font=ui_font(11, "bold"),
            bg=COLOR_BRAND_SOFT,
            fg=COLOR_PRIMARY,
            padx=SPACE_4,
            pady=SPACE_2,
            highlightthickness=1,
            highlightbackground=COLOR_BRAND_SOFT,
        )
        icon.pack()

        self.file_title_label = tk.Label(
            upload_area,
            text="Selecione o PDF do SAJ",
            font=ui_font(12, "bold"),
            bg=COLOR_CARD,
            fg=COLOR_TEXT,
            wraplength=520,
            justify="center",
        )
        self.file_title_label.pack()

        self.file_path_label = tk.Label(
            upload_area,
            text="Clique ou arraste o PDF aqui. A copia pesquisavel sera salva na pasta do app.",
            font=ui_font(10),
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            wraplength=520,
        )
        self.file_path_label.pack(pady=(SPACE_2, SPACE_5))

        self.btn_select = self.make_action_button(
            upload_area,
            text="Selecionar PDF do SAJ",
            command=self.select_pdf,
            primary=True,
        )
        self.btn_select.pack(pady=(0, 4), ipadx=6)

    # --------------------------------------------------------

    def create_markdown_card(self, parent):
        card = self.make_card(parent, "Markdown automatico", fill="x", pady=(SPACE_5, 0))

        panel = tk.Frame(
            card,
            bg=COLOR_BRAND_SOFT,
            highlightthickness=2,
            highlightbackground=COLOR_BRAND_SOFT,
            highlightcolor=COLOR_BRAND_SOFT,
        )
        panel.pack(fill="x", padx=SPACE_5, pady=(0, SPACE_5))

        badge = tk.Label(
            panel,
            text="MD",
            bg=COLOR_CARD,
            fg=COLOR_PRIMARY,
            font=ui_font(10, "bold"),
            width=5,
            padx=SPACE_3,
            pady=SPACE_2,
        )
        badge.pack(side="left", padx=(SPACE_4, SPACE_3), pady=SPACE_4)

        text_area = tk.Frame(panel, bg=COLOR_BRAND_SOFT)
        text_area.pack(side="left", fill="both", expand=True, padx=(0, SPACE_4), pady=SPACE_4)

        title = tk.Label(
            text_area,
            text="Geracao automatica apos validar o OCR",
            bg=COLOR_BRAND_SOFT,
            fg=COLOR_TEXT,
            font=ui_font(10, "bold"),
            anchor="w",
        )
        title.pack(anchor="w", fill="x")

        description = tk.Label(
            text_area,
            text="O app mantem o PDF pesquisavel e salva tambem um arquivo .md leve com todo o texto extraido.",
            bg=COLOR_BRAND_SOFT,
            fg=COLOR_MUTED,
            font=ui_font(9),
            anchor="w",
            wraplength=520,
            justify="left",
        )
        description.pack(anchor="w", fill="x", pady=(3, 0))

    # --------------------------------------------------------

    def configure_drag_and_drop(self):
        targets = [self.root]
        if self.upload_area is not None:
            targets.append(self.upload_area)

        registered = any(self.register_tkdnd_target(widget) for widget in targets)
        if not registered:
            registered = any(self.register_windnd_target(widget) for widget in targets)

        if registered:
            self.log("Arraste um PDF para qualquer area da janela para iniciar.")
        else:
            message = "Arrastar e soltar indisponivel; use o botao Selecionar PDF."
            if DND_ERROR:
                message = f"{message} Detalhe: {DND_ERROR}"
            self.log(message)

    # --------------------------------------------------------

    def register_tkdnd_target(self, widget) -> bool:
        if DND_FILES is None or not hasattr(widget, "drop_target_register"):
            return False

        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self.handle_tkdnd_drop)
            return True
        except Exception:
            return False

    # --------------------------------------------------------

    def register_windnd_target(self, widget) -> bool:
        if windnd is None:
            return False

        try:
            windnd.hook_dropfiles(widget, func=self.handle_windnd_drop)
            return True
        except Exception:
            return False

    # --------------------------------------------------------

    def handle_windnd_drop(self, files):
        try:
            if not files:
                return

            path = Path(os.fsdecode(files[0]))
            self.after_ui(0, lambda: self.load_pdf(path))
        except Exception as e:
            self.log(f"Falha ao receber arquivo arrastado: {e}")

    # --------------------------------------------------------

    def handle_tkdnd_drop(self, event):
        try:
            dropped_files = self.root.tk.splitlist(event.data)
            if not dropped_files:
                return

            self.load_pdf(Path(dropped_files[0]))
        except Exception as e:
            self.log(f"Falha ao receber arquivo arrastado: {e}")

    # --------------------------------------------------------

    def create_progress_card(self, parent):
        card = self.make_card(parent, "Progresso", fill="x", pady=(SPACE_5, 0))

        summary = tk.Frame(card, bg=COLOR_CARD)
        summary.pack(fill="x", padx=SPACE_5, pady=(0, SPACE_4))

        self.progress_percent_label = tk.Label(
            summary,
            text="0%",
            bg=COLOR_CARD,
            fg=COLOR_PRIMARY,
            font=ui_font(34, "bold"),
            width=4,
            anchor="w",
        )
        self.progress_percent_label.pack(side="left", padx=(0, SPACE_4))

        self.status_label = tk.Label(
            summary,
            text="Aguardando selecao do PDF...",
            bg=COLOR_CARD,
            fg=COLOR_TEXT,
            font=ui_font(13, "bold"),
            anchor="w",
            wraplength=760,
            justify="left",
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        self.progress = ttk.Progressbar(
            card,
            mode="determinate",
            maximum=100,
            value=0,
        )
        self.progress.pack(fill="x", padx=SPACE_5, pady=(0, SPACE_5), ipady=5)

    # --------------------------------------------------------

    def create_validation_card(self, parent):
        card = self.make_card(parent, "Garantia", fill="x")

        self.validation_status_label = tk.Label(
            card,
            text="Pronto para receber um PDF",
            bg=COLOR_CARD,
            fg=COLOR_MUTED,
            font=ui_font(9, "bold"),
            wraplength=280,
            justify="left",
            anchor="w",
        )
        self.validation_status_label.pack(anchor="w", fill="x", padx=SPACE_5, pady=(0, SPACE_5))

    # --------------------------------------------------------

    def create_actions_card(self, parent):
        card = self.make_card(parent, "Resultado", fill="x", pady=(SPACE_5, 0))

        self.btn_cancel = self.make_action_button(
            card,
            text="Cancelar OCR",
            command=self.cancel_processing,
            primary=False,
        )
        self.btn_cancel.config(state="disabled")
        self.btn_cancel.pack(fill="x", padx=SPACE_5, pady=(0, SPACE_2))

        self.btn_open_pdf = self.make_action_button(
            card,
            text="Abrir PDF pesquisavel",
            command=self.open_output_pdf,
            primary=False,
        )
        self.btn_open_pdf.config(state="disabled")
        self.btn_open_pdf.pack(fill="x", padx=SPACE_5, pady=(0, SPACE_2))

        self.btn_open_markdown = self.make_action_button(
            card,
            text="Abrir Markdown",
            command=self.open_output_markdown,
            primary=False,
        )
        self.btn_open_markdown.config(state="disabled")
        self.btn_open_markdown.pack(fill="x", padx=SPACE_5, pady=(0, SPACE_2))

        self.btn_open_folder = self.make_action_button(
            card,
            text="Abrir pasta",
            command=self.open_output_folder,
            primary=False,
        )
        self.btn_open_folder.config(state="disabled")
        self.btn_open_folder.pack(fill="x", padx=SPACE_5, pady=(0, SPACE_5))

    # --------------------------------------------------------

    def create_help_card(self, parent):
        card = self.make_card(parent, "Seguranca", fill="both", expand=True, pady=(SPACE_5, 0))

        text = (
            "O arquivo original nao e alterado.\n\n"
            "Ao selecionar o PDF, o processamento comeca automaticamente.\n\n"
            "A copia PDF so e liberada depois de conferir paginas, tamanho e texto pesquisavel.\n\n"
            "O Markdown e gerado a partir do PDF OCR validado."
        )

        label = tk.Label(
            card,
            text=text,
            wraplength=280,
            justify="left",
            bg=COLOR_CARD,
            fg=COLOR_TEXT,
            font=ui_font(10),
            anchor="nw",
        )
        label.pack(anchor="nw", fill="x", padx=SPACE_5, pady=(0, SPACE_5))

    # --------------------------------------------------------

    def create_log_card(self, parent):
        card = self.make_card(parent, "Log tecnico", fill="both", expand=True, pady=(SPACE_5, 0))

        self.log_text = tk.Text(
            card,
            height=10,
            wrap="word",
            state="disabled",
            bg=COLOR_LOG_BG,
            fg=COLOR_LOG_TEXT,
            insertbackground=COLOR_TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER,
            font=("Consolas", 10),
        )
        self.log_text.pack(fill="both", expand=True, padx=SPACE_5, pady=(0, SPACE_5))

    # --------------------------------------------------------

    def select_pdf(self):
        pdf_file = filedialog.askopenfilename(
            title="Selecione o PDF",
            filetypes=[("Arquivos PDF", "*.pdf")],
        )

        if not pdf_file:
            return

        self.load_pdf(Path(pdf_file))

    # --------------------------------------------------------

    def load_pdf(self, pdf_path: Path):
        if self.processing_busy:
            self.log("Arquivo ignorado: processamento em andamento.")
            return

        if pdf_path.suffix.lower() != ".pdf":
            messagebox.showwarning("Atencao", "Solte ou selecione um arquivo PDF.")
            return

        job_id = self.current_job_id + 1
        self.current_job_id = job_id
        self.processing_busy = True
        self.selected_pdf = pdf_path
        self.output_pdf = None
        self.output_markdown = None
        self.last_report = None

        self.file_title_label.config(text=self.selected_pdf.name)
        self.file_path_label.config(text=str(self.selected_pdf))

        self.btn_open_pdf.config(state="disabled")
        self.btn_open_markdown.config(state="disabled")
        self.btn_open_folder.config(state="disabled")

        self.set_progress(0)
        self.set_validation_status("PDF recebido. Iniciando processamento...", state="progress")
        self.log(f"PDF selecionado: {self.selected_pdf}")
        self.after_ui(100, lambda: self.start_processing(job_id))

    # --------------------------------------------------------

    def validate_inputs(self) -> tuple[bool, str]:
        if self.selected_pdf is None:
            return False, "Selecione um PDF primeiro."

        if not self.selected_pdf.exists():
            return False, "O PDF selecionado nao existe."

        if self.selected_pdf.suffix.lower() != ".pdf":
            return False, "O arquivo selecionado precisa ser um PDF."

        ok_tess, msg_tess = check_tesseract(DEFAULT_LANGUAGE)
        self.log(msg_tess)

        if not ok_tess:
            return False, msg_tess

        return True, "OK"

    # --------------------------------------------------------

    def start_processing(self, job_id: int):
        if job_id != self.current_job_id:
            return

        valid, message = self.validate_inputs()

        if not valid:
            self.processing_busy = False
            messagebox.showerror("Atencao", message)
            return

        self.cancel_event = threading.Event()
        cancel_event = self.cancel_event
        input_pdf = self.selected_pdf

        self.btn_select.config(state="disabled")
        self.btn_open_pdf.config(state="disabled")
        self.btn_open_markdown.config(state="disabled")
        self.btn_open_folder.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.btn_select.config(text="Processando PDF...")

        self.last_report = None
        self.set_progress(0)
        self.set_status("Iniciando OCR...")
        self.set_validation_status("Processando...", state="progress")
        self.log("Iniciando processamento...")

        self.worker_thread = threading.Thread(
            target=self.processing_worker,
            args=(job_id, input_pdf, cancel_event),
            daemon=True,
        )
        self.active_worker_threads.add(self.worker_thread)
        self.worker_thread.start()

    # --------------------------------------------------------

    def processing_worker(
        self,
        job_id: int,
        input_pdf: Path | None,
        cancel_event: threading.Event,
    ):
        try:
            if input_pdf is None:
                raise RuntimeError("Nenhum PDF selecionado.")

            output_pdf = safe_output_path(input_pdf)
            markdown_path = markdown_output_path_for_pdf(output_pdf)
            self.after_ui(0, lambda: self.set_outputs_for_job(job_id, output_pdf, markdown_path))

            self.log(f"Arquivo de entrada: {input_pdf}")
            self.log(f"Arquivo de saida: {output_pdf}")
            self.log(f"Arquivo Markdown: {markdown_path}")
            self.log("Processamento: fidelidade alta para PDF do SAJ")
            self.log(f"Qualidade interna: {DEFAULT_DPI} DPI")
            self.status_queue.put("Preparando OCR...")

            report = run_compatibility_mode(
                input_pdf=input_pdf,
                output_pdf=output_pdf,
                output_markdown=markdown_path,
                language=DEFAULT_LANGUAGE,
                dpi=DEFAULT_DPI,
                progress_callback=self.report_step,
                progress_percent_callback=lambda value: self.progress_queue.put(value),
                cancel_event=cancel_event,
            )

            self.log(
                "Validacao: "
                f"{report.pages} paginas, {report.pages_with_text} com texto pesquisavel."
            )
            for warning in report.warnings:
                self.log(f"Alerta: {warning}")

            self.log("Processamento concluido.")
            self.after_ui(0, lambda: self.processing_success(job_id, report, output_pdf, markdown_path))

        except ProcessingCancelled as e:
            self.log(str(e))
            self.after_ui(0, lambda: self.processing_cancelled(job_id))

        except Exception as e:
            error_message = str(e)
            self.log(f"Erro: {error_message}")
            self.after_ui(0, lambda: self.processing_error(job_id, error_message))

        finally:
            self.active_worker_threads.discard(threading.current_thread())
            self.after_ui(0, lambda: self.finish_processing(job_id))

    # --------------------------------------------------------

    def is_active_job(self, job_id: int) -> bool:
        return job_id == self.current_job_id and job_id not in self.cancelled_job_ids

    # --------------------------------------------------------

    def set_outputs_for_job(self, job_id: int, output_pdf: Path, markdown_path: Path):
        if self.is_active_job(job_id):
            self.output_pdf = output_pdf
            self.output_markdown = markdown_path

    # --------------------------------------------------------

    def processing_success(
        self,
        job_id: int,
        report: PdfValidationReport,
        output_pdf: Path,
        markdown_path: Path,
    ):
        if not self.is_active_job(job_id):
            return

        self.last_report = report
        self.output_pdf = output_pdf
        self.output_markdown = markdown_path
        self.set_status("PDF OCR e Markdown criados.")
        self.set_progress(100)

        self.btn_open_pdf.config(state="normal")
        self.btn_open_markdown.config(state="normal")
        self.btn_open_folder.config(state="normal")

        if self.last_report:
            validation_text = (
                f"OK: {self.last_report.pages} paginas | "
                f"{self.last_report.pages_with_text} com texto pesquisavel | Markdown gerado"
            )
            if self.last_report.warnings:
                validation_text += f" | {len(self.last_report.warnings)} alerta(s)"
            state = "warning" if self.last_report.warnings else "success"
            self.set_validation_status(validation_text, state=state)

        messagebox.showinfo(
            "Concluido",
            "Arquivos criados e validados:\n\n"
            f"PDF: {self.output_pdf}\n"
            f"Markdown: {self.output_markdown}",
        )

    # --------------------------------------------------------

    def processing_error(self, job_id: int, error_message: str):
        if not self.is_active_job(job_id):
            return

        self.set_status("Erro ao processar PDF.")
        self.set_validation_status("Falha na validacao ou no processamento", state="critical")
        messagebox.showerror("Erro ao processar PDF", error_message)

    # --------------------------------------------------------

    def processing_cancelled(self, job_id: int):
        if job_id != self.current_job_id:
            return

        self.set_status("OCR cancelado.")
        self.set_validation_status(
            "Processamento cancelado. Nenhum PDF final foi liberado.",
            state="warning",
        )
        self.log("OCR cancelado pelo usuario.")

    # --------------------------------------------------------

    def cancel_processing(self):
        if not self.processing_busy:
            return

        self.cancel_event.set()
        self.cancelled_job_ids.add(self.current_job_id)
        self.processing_busy = False
        self.btn_cancel.config(state="disabled")
        self.btn_select.config(state="normal")
        self.btn_select.config(text="Selecionar outro PDF")
        self.btn_open_pdf.config(state="disabled")
        self.btn_open_markdown.config(state="disabled")
        self.btn_open_folder.config(state="disabled")
        self.output_pdf = None
        self.output_markdown = None
        self.last_report = None
        self.set_status("OCR cancelado. Selecione outro PDF.")
        self.set_validation_status("Cancelado. Pronto para receber outro PDF.", state="warning")
        self.log("Cancelamento solicitado. Voce ja pode selecionar ou arrastar outro PDF.")

    # --------------------------------------------------------

    def finish_processing(self, job_id: int):
        if job_id != self.current_job_id:
            return

        self.processing_busy = False
        self.cancelled_job_ids.discard(job_id)
        self.btn_select.config(state="normal")
        self.btn_cancel.config(state="disabled")
        self.btn_select.config(text="Selecionar outro PDF")

    # --------------------------------------------------------

    def open_output_pdf(self):
        if self.output_pdf and self.output_pdf.exists():
            open_file(self.output_pdf)
        else:
            messagebox.showwarning("Atencao", "Nenhum PDF final encontrado.")

    # --------------------------------------------------------

    def open_output_markdown(self):
        if self.output_markdown and self.output_markdown.exists():
            open_file(self.output_markdown)
        else:
            messagebox.showwarning("Atencao", "Nenhum Markdown final encontrado.")

    # --------------------------------------------------------

    def open_output_folder(self):
        if self.output_markdown:
            open_folder(self.output_markdown)
        elif self.output_pdf:
            open_folder(self.output_pdf)
        elif self.selected_pdf:
            open_folder(self.selected_pdf)
        else:
            messagebox.showwarning("Atencao", "Nenhuma pasta disponivel.")

    # --------------------------------------------------------

    def log(self, text: str):
        self.log_queue.put(text)

    # --------------------------------------------------------

    def report_step(self, text: str):
        self.log(text)
        self.status_queue.put(text)

    # --------------------------------------------------------

    def set_status(self, text: str):
        self.status_label.config(text=text)

    # --------------------------------------------------------

    def set_validation_status(self, text: str, state: str):
        state_colors = {
            "success": (COLOR_SUCCESS_BG, COLOR_SUCCESS),
            "progress": (COLOR_WARNING_BG, COLOR_WARNING),
            "warning": (COLOR_WARNING_BG, COLOR_WARNING),
            "critical": (COLOR_BRAND_SOFT, COLOR_PRIMARY),
            "neutral": (COLOR_CARD_ALT, COLOR_MUTED),
        }
        background, color = state_colors.get(state, state_colors["neutral"])
        self.validation_status_label.config(text=text, fg=color, bg=background, padx=SPACE_3, pady=SPACE_2)

    # --------------------------------------------------------

    def set_progress(self, value: int):
        value = max(0, min(100, int(value)))
        self.progress["value"] = value
        self.progress_percent_label.config(text=f"{value}%")

    # --------------------------------------------------------

    def process_queues(self):
        if self.closing:
            return

        try:
            try:
                while True:
                    msg = self.log_queue.get_nowait()
                    self.append_log(msg)
            except queue.Empty:
                pass

            try:
                while True:
                    status = self.status_queue.get_nowait()
                    self.set_status(status)
            except queue.Empty:
                pass

            try:
                while True:
                    value = self.progress_queue.get_nowait()
                    self.set_progress(value)
            except queue.Empty:
                pass
        except tk.TclError:
            return

        self.after_ui(120, self.process_queues)

    # --------------------------------------------------------

    def append_log(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {text}\n"

        self.log_text.config(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.config(state="disabled")


# ============================================================
# MAIN
# ============================================================

def main():
    root = create_root_window()
    AutoOCRApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
