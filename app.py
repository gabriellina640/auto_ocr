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

COLOR_BG = "#07111f"
COLOR_CARD = "#0f1b2e"
COLOR_CARD_ALT = "#0c2f3c"
COLOR_BORDER = "#24445f"
COLOR_PRIMARY = "#0f766e"
COLOR_PRIMARY_DARK = "#115e59"
COLOR_SECONDARY = "#1d4ed8"
COLOR_SECONDARY_DARK = "#1e3a8a"
COLOR_SUCCESS = "#15803d"
COLOR_SUCCESS_DARK = "#166534"
COLOR_WARNING = "#f59e0b"
COLOR_TEXT = "#f8fafc"
COLOR_MUTED = "#cbd5e1"
COLOR_LOG_BG = "#020617"
COLOR_LOG_TEXT = "#e2e8f0"
COLOR_CYAN = "#155e75"


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

    if not base.exists():
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

    image_path = output_base.with_suffix(".png")
    output_pdf = output_base.with_suffix(".pdf")

    image.save(
        image_path,
        format="PNG",
        dpi=(dpi, dpi),
    )

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


def publish_validated_pdf(input_pdf: Path, temp_pdf: Path, output_pdf: Path) -> PdfValidationReport:
    report = validate_pdf_output(input_pdf, temp_pdf)
    os.replace(temp_pdf, output_pdf)
    return report


def format_file_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def optimize_pdf_size(pdf_path: Path, progress_callback) -> Path:
    original_size = pdf_path.stat().st_size
    best_path = pdf_path
    best_size = original_size

    def accept_candidate(candidate_path: Path) -> bool:
        nonlocal best_path, best_size

        if not candidate_path.exists() or candidate_path.stat().st_size == 0:
            candidate_path.unlink(missing_ok=True)
            return False

        try:
            with fitz.open(str(candidate_path)):
                pass
            PdfReader(str(candidate_path))
        except Exception:
            candidate_path.unlink(missing_ok=True)
            return False

        candidate_size = candidate_path.stat().st_size
        if candidate_size < best_size:
            if best_path != pdf_path:
                best_path.unlink(missing_ok=True)
            best_path = candidate_path
            best_size = candidate_size
            return True

        candidate_path.unlink(missing_ok=True)
        return False

    mupdf_path = make_temp_output_path(pdf_path)
    try:
        with fitz.open(str(best_path)) as document:
            document.save(
                str(mupdf_path),
                garbage=4,
                clean=True,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                use_objstms=1,
                compression_effort=9,
            )
        accept_candidate(mupdf_path)
    except Exception as e:
        mupdf_path.unlink(missing_ok=True)
        progress_callback(f"Limpeza estrutural nao aplicada: {e}")

    if best_path == pdf_path:
        progress_callback("Compactacao sem ganho relevante; mantendo PDF validado.")
        return pdf_path

    pdf_path.unlink(missing_ok=True)
    progress_callback(
        "Tamanho reduzido: "
        f"{format_file_size(original_size)} -> {format_file_size(best_size)}."
    )
    return best_path


# ============================================================
# PROCESSAMENTO OCR
# ============================================================

def run_compatibility_mode(
    input_pdf: Path,
    output_pdf: Path,
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
        progress_callback("Compactando PDF final...")
        temp_output = optimize_pdf_size(temp_output, progress_callback)
        raise_if_cancelled(cancel_event)
        progress_percent_callback(98)
        progress_callback("Validando PDF final...")
        report = publish_validated_pdf(input_pdf, temp_output, output_pdf)
        progress_percent_callback(100)
        progress_callback("PDF OCR criado e validado com sucesso.")
        return report

    finally:
        document.close()
        cleanup_temp_tree(temp_dir, progress_callback)
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)


# ============================================================
# INTERFACE
# ============================================================

class ActionButton(tk.Frame):
    def __init__(self, parent, text: str, command, primary: bool = False):
        super().__init__(parent, bd=0, highlightthickness=0)
        self.command = command
        self.primary = primary
        self.state = "normal"
        self.text = text

        self.normal_bg = COLOR_PRIMARY if primary else COLOR_SECONDARY
        self.active_bg = COLOR_PRIMARY_DARK if primary else COLOR_SECONDARY_DARK
        self.disabled_bg = "#334155"
        self.normal_fg = "#ffffff"
        self.disabled_fg = "#e2e8f0"

        self.label = tk.Label(
            self,
            text=text,
            font=("Segoe UI", 10, "bold"),
            padx=18,
            pady=13,
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
        self.root.geometry("1180x820")
        self.root.minsize(980, 720)
        self.root.configure(bg=COLOR_BG)

        self.selected_pdf: Path | None = None
        self.output_pdf: Path | None = None
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
        self.progress_queue: queue.Queue[int] = queue.Queue()

        self.root.protocol("WM_DELETE_WINDOW", self.close_app)
        self.setup_style()
        self.create_layout()
        self.configure_drag_and_drop()
        self.process_queues()

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

        default_font = ("Segoe UI", 10)
        title_font = ("Segoe UI", 28, "bold")
        heading_font = ("Segoe UI", 13, "bold")
        button_font = ("Segoe UI", 10, "bold")

        style.configure(".", font=default_font, background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("Title.TLabel", font=title_font, background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), background=COLOR_BG, foreground=COLOR_MUTED)
        style.configure("CardTitle.TLabel", font=heading_font, background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("CardText.TLabel", background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("Hint.TLabel", font=("Segoe UI", 9), background=COLOR_CARD, foreground=COLOR_MUTED)
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"), background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("Success.TLabel", font=("Segoe UI", 9, "bold"), background=COLOR_CARD, foreground="#86efac")
        style.configure("Warning.TLabel", font=("Segoe UI", 9, "bold"), background=COLOR_CARD, foreground="#fbbf24")
        style.configure("Primary.TButton", font=button_font, padding=(14, 10))
        style.configure("Secondary.TButton", padding=(10, 7))
        style.configure("TProgressbar", troughcolor="#1e293b", background="#22d3ee", bordercolor="#1e293b")

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
            label = ttk.Label(card, text=title, style="CardTitle.TLabel")
            label.pack(anchor="w", padx=18, pady=(16, 8))

        return card

    # --------------------------------------------------------

    def make_action_button(self, parent, text: str, command, primary: bool = False) -> ActionButton:
        return ActionButton(parent, text=text, command=command, primary=primary)

    # --------------------------------------------------------

    def create_layout(self):
        main = tk.Frame(self.root, bg=COLOR_BG)
        main.pack(fill="both", expand=True, padx=26, pady=24)

        header = tk.Frame(main, bg=COLOR_BG)
        header.pack(fill="x")

        badge = tk.Label(
            header,
            text="SAJ OCR",
            bg=COLOR_SUCCESS,
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
        )
        badge.pack(anchor="w", pady=(0, 8))

        title = ttk.Label(header, text="Auto OCR PDF", style="Title.TLabel")
        title.pack(anchor="w")

        subtitle = ttk.Label(
            header,
            text="Selecione o PDF do SAJ. O app gera uma copia fiel, pesquisavel e validada.",
            style="Subtitle.TLabel",
        )
        subtitle.pack(anchor="w", pady=(4, 0))

        content = tk.Frame(main, bg=COLOR_BG)
        content.pack(fill="both", expand=True, pady=(22, 0))
        content.grid_columnconfigure(0, weight=3, minsize=560)
        content.grid_columnconfigure(1, weight=1, minsize=320)
        content.grid_rowconfigure(0, weight=1)

        left = tk.Frame(content, bg=COLOR_BG)
        left.grid(row=0, column=0, sticky="nsew")

        right = tk.Frame(content, bg=COLOR_BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(22, 0))

        self.create_file_card(left)
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
            bg=COLOR_CARD_ALT,
            highlightbackground="#22d3ee",
            highlightthickness=2,
            height=220,
        )
        self.upload_area = upload_area
        upload_area.pack(fill="x", padx=18, pady=(4, 18))
        upload_area.pack_propagate(False)

        icon = tk.Label(
            upload_area,
            text="PDF",
            font=("Segoe UI", 18, "bold"),
            bg=COLOR_CYAN,
            fg="#ffffff",
            width=5,
            height=1,
        )
        icon.pack(pady=(26, 10))

        self.file_title_label = tk.Label(
            upload_area,
            text="Selecione o PDF do SAJ",
            font=("Segoe UI", 12, "bold"),
            bg=COLOR_CARD_ALT,
            fg=COLOR_TEXT,
        )
        self.file_title_label.pack()

        self.file_path_label = tk.Label(
            upload_area,
            text="Clique ou arraste o PDF aqui. A copia pesquisavel sera salva na pasta do app.",
            font=("Segoe UI", 10),
            bg=COLOR_CARD_ALT,
            fg=COLOR_MUTED,
            wraplength=820,
        )
        self.file_path_label.pack(pady=(5, 16))

        self.btn_select = self.make_action_button(
            upload_area,
            text="Selecionar PDF do SAJ",
            command=self.select_pdf,
            primary=True,
        )
        self.btn_select.pack(pady=(0, 4), ipadx=6)

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
        card = self.make_card(parent, "Progresso", fill="x", pady=(18, 0))

        self.status_label = ttk.Label(
            card,
            text="Aguardando selecao do PDF...",
            style="Status.TLabel",
        )
        self.status_label.pack(anchor="w", padx=18, pady=(2, 8))

        self.progress = ttk.Progressbar(
            card,
            mode="determinate",
            maximum=100,
            value=0,
        )
        self.progress.pack(fill="x", padx=18, pady=(0, 6))

        self.progress_percent_label = ttk.Label(
            card,
            text="0%",
            style="Hint.TLabel",
        )
        self.progress_percent_label.pack(anchor="e", padx=18, pady=(0, 10))

        self.btn_cancel = self.make_action_button(
            card,
            text="Cancelar OCR",
            command=self.cancel_processing,
            primary=False,
        )
        self.btn_cancel.config(state="disabled")
        self.btn_cancel.pack(anchor="w", padx=18, pady=(0, 16))

    # --------------------------------------------------------

    def create_validation_card(self, parent):
        card = self.make_card(parent, "Garantia", fill="x")

        self.validation_status_label = ttk.Label(
            card,
            text="Pronto para receber um PDF",
            style="Hint.TLabel",
            wraplength=280,
        )
        self.validation_status_label.pack(anchor="w", padx=18, pady=(0, 16))

    # --------------------------------------------------------

    def create_actions_card(self, parent):
        card = self.make_card(parent, "Resultado", fill="x", pady=(18, 0))

        self.btn_open_pdf = self.make_action_button(
            card,
            text="Abrir PDF pesquisavel",
            command=self.open_output_pdf,
            primary=False,
        )
        self.btn_open_pdf.config(state="disabled")
        self.btn_open_pdf.pack(fill="x", padx=18, pady=(0, 8))

        self.btn_open_folder = self.make_action_button(
            card,
            text="Abrir pasta",
            command=self.open_output_folder,
            primary=False,
        )
        self.btn_open_folder.config(state="disabled")
        self.btn_open_folder.pack(fill="x", padx=18, pady=(0, 18))

    # --------------------------------------------------------

    def create_help_card(self, parent):
        card = self.make_card(parent, "Seguranca", fill="both", expand=True, pady=(18, 0))

        text = (
            "O arquivo original nao e alterado.\n\n"
            "Ao selecionar o PDF, o processamento comeca automaticamente.\n\n"
            "A copia so e liberada depois de conferir paginas, tamanho e texto pesquisavel."
        )

        label = ttk.Label(
            card,
            text=text,
            wraplength=280,
            justify="left",
            style="CardText.TLabel",
        )
        label.pack(anchor="nw", padx=18, pady=(0, 18))

    # --------------------------------------------------------

    def create_log_card(self, parent):
        card = self.make_card(parent, "Log tecnico", fill="both", expand=True, pady=(18, 0))

        self.log_text = tk.Text(
            card,
            height=10,
            wrap="word",
            state="disabled",
            bg=COLOR_LOG_BG,
            fg=COLOR_LOG_TEXT,
            insertbackground="#ffffff",
            relief="flat",
            borderwidth=0,
            font=("Consolas", 10),
        )
        self.log_text.pack(fill="both", expand=True, padx=18, pady=(0, 18))

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
        self.last_report = None

        self.file_title_label.config(text=self.selected_pdf.name)
        self.file_path_label.config(text=str(self.selected_pdf))

        self.btn_open_pdf.config(state="disabled")
        self.btn_open_folder.config(state="disabled")

        self.set_progress(0)
        self.set_validation_status("PDF recebido. Iniciando processamento...", warning=False)
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
        self.btn_open_folder.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.btn_select.config(text="Processando PDF...")

        self.last_report = None
        self.set_progress(0)
        self.set_status("Iniciando OCR...")
        self.set_validation_status("Processando...", warning=False)
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
            self.after_ui(0, lambda: self.set_output_for_job(job_id, output_pdf))

            self.log(f"Arquivo de entrada: {input_pdf}")
            self.log(f"Arquivo de saida: {output_pdf}")
            self.log("Processamento: fidelidade alta para PDF do SAJ")
            self.log(f"Qualidade interna: {DEFAULT_DPI} DPI")

            report = run_compatibility_mode(
                input_pdf=input_pdf,
                output_pdf=output_pdf,
                language=DEFAULT_LANGUAGE,
                dpi=DEFAULT_DPI,
                progress_callback=self.log,
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
            self.after_ui(0, lambda: self.processing_success(job_id, report, output_pdf))

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

    def set_output_for_job(self, job_id: int, output_pdf: Path):
        if self.is_active_job(job_id):
            self.output_pdf = output_pdf

    # --------------------------------------------------------

    def processing_success(self, job_id: int, report: PdfValidationReport, output_pdf: Path):
        if not self.is_active_job(job_id):
            return

        self.last_report = report
        self.output_pdf = output_pdf
        self.set_status("PDF OCR criado e validado.")
        self.set_progress(100)

        self.btn_open_pdf.config(state="normal")
        self.btn_open_folder.config(state="normal")

        if self.last_report:
            validation_text = (
                f"OK: {self.last_report.pages} paginas | "
                f"{self.last_report.pages_with_text} com texto pesquisavel"
            )
            if self.last_report.warnings:
                validation_text += f" | {len(self.last_report.warnings)} alerta(s)"
            self.set_validation_status(validation_text, warning=bool(self.last_report.warnings))

        messagebox.showinfo(
            "Concluido",
            f"PDF pesquisavel criado e validado:\n\n{self.output_pdf}",
        )

    # --------------------------------------------------------

    def processing_error(self, job_id: int, error_message: str):
        if not self.is_active_job(job_id):
            return

        self.set_status("Erro ao processar PDF.")
        self.set_validation_status("Falha na validacao ou no processamento", warning=True)
        messagebox.showerror("Erro ao processar PDF", error_message)

    # --------------------------------------------------------

    def processing_cancelled(self, job_id: int):
        if job_id != self.current_job_id:
            return

        self.set_status("OCR cancelado.")
        self.set_validation_status("Processamento cancelado. Nenhum PDF final foi liberado.", warning=True)
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
        self.btn_open_folder.config(state="disabled")
        self.output_pdf = None
        self.last_report = None
        self.set_status("OCR cancelado. Selecione outro PDF.")
        self.set_validation_status("Cancelado. Pronto para receber outro PDF.", warning=True)
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

    def open_output_folder(self):
        if self.output_pdf:
            open_folder(self.output_pdf)
        elif self.selected_pdf:
            open_folder(self.selected_pdf)
        else:
            messagebox.showwarning("Atencao", "Nenhuma pasta disponivel.")

    # --------------------------------------------------------

    def log(self, text: str):
        self.log_queue.put(text)

    # --------------------------------------------------------

    def set_status(self, text: str):
        self.status_label.config(text=text)

    # --------------------------------------------------------

    def set_validation_status(self, text: str, warning: bool):
        style = "Warning.TLabel" if warning else "Success.TLabel"
        self.validation_status_label.config(text=text, style=style)

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
                    self.set_status(msg)
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
