import os
import sys
import shutil
import queue
import tempfile
import threading
import subprocess
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from pypdf import PdfWriter, PdfReader


APP_NAME = "Auto OCR PDF"
APP_VERSION = "1.2.0"
DEFAULT_LANGUAGE = "por"
DEFAULT_DPI = 400
PAGE_SIZE_TOLERANCE = 2.0

COLOR_BG = "#f6f8fb"
COLOR_CARD = "#ffffff"
COLOR_CARD_ALT = "#ecfeff"
COLOR_BORDER = "#d8e0ea"
COLOR_PRIMARY = "#2563eb"
COLOR_PRIMARY_DARK = "#1d4ed8"
COLOR_SUCCESS = "#15803d"
COLOR_SUCCESS_DARK = "#166534"
COLOR_WARNING = "#f59e0b"
COLOR_TEXT = "#111827"
COLOR_MUTED = "#64748b"
COLOR_LOG_BG = "#0f172a"
COLOR_LOG_TEXT = "#e5e7eb"
COLOR_CYAN = "#0e7490"


@dataclass(frozen=True)
class PdfValidationReport:
    pages: int
    pages_with_text: int
    warnings: list[str]


# ============================================================
# UTILITARIOS
# ============================================================

def is_windows() -> bool:
    return os.name == "nt"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


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
        elif is_macos():
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as e:
        messagebox.showerror("Erro", f"Nao foi possivel abrir o arquivo:\n\n{e}")


def open_folder(path: Path):
    try:
        folder = path if path.is_dir() else path.parent

        if is_windows():
            os.startfile(folder)
        elif is_macos():
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
    except Exception as e:
        messagebox.showerror("Erro", f"Nao foi possivel abrir a pasta:\n\n{e}")


def safe_output_path(input_pdf: Path) -> Path:
    base = input_pdf.with_name(f"{input_pdf.stem}_OCR.pdf")

    if not base.exists():
        return base

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return input_pdf.with_name(f"{input_pdf.stem}_OCR_{timestamp}.pdf")


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


def run_tesseract_pdf(image: Image.Image, output_base: Path, language: str, dpi: int) -> Path:
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
    result = subprocess.run(
        command,
        capture_output=True,
        env=env,
    )

    stderr = result.stderr.decode(errors="replace").strip()
    stdout = result.stdout.decode(errors="replace").strip()

    cli_detail = stderr or stdout or "sem detalhe tecnico"
    if output_pdf.exists() and output_pdf.stat().st_size > 0:
        try:
            PdfReader(str(output_pdf))
            return output_pdf
        except Exception as e:
            cli_detail = f"PDF OCR gerado pelo CLI estava invalido: {e}. {cli_detail}"
            output_pdf.unlink(missing_ok=True)

    try:
        pdf_bytes = pytesseract.image_to_pdf_or_hocr(
            image,
            extension="pdf",
            lang=language,
            config="--psm 3 -c preserve_interword_spaces=1",
        )
        output_pdf.write_bytes(pdf_bytes)
        PdfReader(str(output_pdf))
        return output_pdf
    except Exception as e:
        output_pdf.unlink(missing_ok=True)
        if result.returncode != 0:
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
) -> PdfValidationReport:
    """
    Modo compatibilidade:
    Renderiza cada pagina como imagem e aplica OCR.
    Preserva pagina, proporcao e dimensao fisica para reduzir risco visual.
    """
    progress_callback("Abrindo PDF...")

    document = fitz.open(str(input_pdf))
    total_pages = document.page_count

    if total_pages == 0:
        document.close()
        raise RuntimeError("O PDF nao possui paginas.")

    writer = PdfWriter()
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    temp_dir = Path(tempfile.mkdtemp(prefix="auto_ocr_pages_", dir=str(output_pdf.parent)))
    temp_output = make_temp_output_path(output_pdf)

    try:
        for page_index in range(total_pages):
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
            )

            reader = PdfReader(str(temp_page_pdf))
            ocr_page = reader.pages[0]
            ocr_page.scale_to(float(source_rect.width), float(source_rect.height))
            writer.add_page(ocr_page)

            percent = int((page_number / total_pages) * 90)
            progress_percent_callback(percent)

        progress_callback("Salvando PDF temporario...")
        with open(temp_output, "wb") as f:
            writer.write(f)

        progress_percent_callback(95)
        progress_callback("Validando PDF final...")
        report = publish_validated_pdf(input_pdf, temp_output, output_pdf)
        progress_percent_callback(100)
        progress_callback("PDF OCR criado e validado com sucesso.")
        return report

    finally:
        document.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)


# ============================================================
# INTERFACE
# ============================================================

class AutoOCRApp:
    def __init__(self, root: tk.Tk):
        self.root = root

        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("980x720")
        self.root.minsize(720, 620)
        self.root.configure(bg=COLOR_BG)

        self.selected_pdf: Path | None = None
        self.output_pdf: Path | None = None
        self.last_report: PdfValidationReport | None = None
        self.worker_thread: threading.Thread | None = None

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.progress_queue: queue.Queue[int] = queue.Queue()

        self.setup_style()
        self.create_layout()
        self.process_queues()

    # --------------------------------------------------------

    def setup_style(self):
        style = ttk.Style()

        try:
            style.theme_use("clam")
        except Exception:
            pass

        default_font = ("Segoe UI", 10)
        title_font = ("Segoe UI", 24, "bold")
        heading_font = ("Segoe UI", 13, "bold")
        button_font = ("Segoe UI", 10, "bold")

        style.configure(".", font=default_font, background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("Title.TLabel", font=title_font, background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10), background=COLOR_BG, foreground=COLOR_MUTED)
        style.configure("CardTitle.TLabel", font=heading_font, background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("CardText.TLabel", background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("Hint.TLabel", font=("Segoe UI", 9), background=COLOR_CARD, foreground=COLOR_MUTED)
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"), background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("Success.TLabel", font=("Segoe UI", 9, "bold"), background=COLOR_CARD, foreground=COLOR_SUCCESS)
        style.configure("Warning.TLabel", font=("Segoe UI", 9, "bold"), background=COLOR_CARD, foreground=COLOR_WARNING)
        style.configure("Primary.TButton", font=button_font, padding=(14, 10))
        style.configure("Secondary.TButton", padding=(10, 7))
        style.configure("TProgressbar", troughcolor="#dbeafe", background=COLOR_PRIMARY, bordercolor="#dbeafe")

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

    def make_action_button(self, parent, text: str, command, primary: bool = False) -> tk.Button:
        bg = COLOR_PRIMARY if primary else "#e2e8f0"
        fg = "#ffffff" if primary else COLOR_TEXT
        active_bg = COLOR_PRIMARY_DARK if primary else "#cbd5e1"

        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active_bg,
            activeforeground=fg,
            disabledforeground="#94a3b8",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            borderwidth=0,
            padx=16,
            pady=10,
            cursor="hand2",
            wraplength=260,
        )

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
        content.grid_columnconfigure(0, weight=3, minsize=360)
        content.grid_columnconfigure(1, weight=1, minsize=240)
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
            highlightbackground="#67e8f9",
            highlightthickness=1,
            height=190,
        )
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
        icon.pack(pady=(22, 8))

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
            text="Escolha o PDF do SAJ para gerar uma copia pesquisavel sem alterar o original.",
            font=("Segoe UI", 9),
            bg=COLOR_CARD_ALT,
            fg=COLOR_MUTED,
            wraplength=680,
        )
        self.file_path_label.pack(pady=(5, 12))

        self.btn_select = self.make_action_button(
            upload_area,
            text="Selecionar PDF do SAJ",
            command=self.select_pdf,
            primary=True,
        )
        self.btn_select.pack(pady=(0, 4), ipadx=6)

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
        self.progress_percent_label.pack(anchor="e", padx=18, pady=(0, 16))

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
            font=("Menlo", 10) if is_macos() else ("Consolas", 10),
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

        self.selected_pdf = Path(pdf_file)
        self.output_pdf = None
        self.last_report = None

        self.file_title_label.config(text=self.selected_pdf.name)
        self.file_path_label.config(text=str(self.selected_pdf))

        self.btn_open_pdf.config(state="disabled")
        self.btn_open_folder.config(state="disabled")

        self.set_progress(0)
        self.set_validation_status("PDF recebido. Iniciando processamento...", warning=False)
        self.log(f"PDF selecionado: {self.selected_pdf}")
        self.root.after(100, self.start_processing)

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

    def start_processing(self):
        valid, message = self.validate_inputs()

        if not valid:
            messagebox.showerror("Atencao", message)
            return

        self.btn_select.config(state="disabled")
        self.btn_open_pdf.config(state="disabled")
        self.btn_open_folder.config(state="disabled")
        self.btn_select.config(text="Processando PDF...")

        self.last_report = None
        self.set_progress(0)
        self.set_status("Iniciando OCR...")
        self.set_validation_status("Processando...", warning=False)
        self.log("Iniciando processamento...")

        self.worker_thread = threading.Thread(
            target=self.processing_worker,
            daemon=True,
        )
        self.worker_thread.start()

    # --------------------------------------------------------

    def processing_worker(self):
        try:
            if self.selected_pdf is None:
                raise RuntimeError("Nenhum PDF selecionado.")

            input_pdf = self.selected_pdf
            output_pdf = safe_output_path(input_pdf)
            self.output_pdf = output_pdf

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
            )

            self.last_report = report
            self.log(
                "Validacao: "
                f"{report.pages} paginas, {report.pages_with_text} com texto pesquisavel."
            )
            for warning in report.warnings:
                self.log(f"Alerta: {warning}")

            self.log("Processamento concluido.")
            self.root.after(0, self.processing_success)

        except Exception as e:
            error_message = str(e)
            self.log(f"Erro: {error_message}")
            self.root.after(0, lambda: self.processing_error(error_message))

        finally:
            self.root.after(0, self.finish_processing)

    # --------------------------------------------------------

    def processing_success(self):
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

    def processing_error(self, error_message: str):
        self.set_status("Erro ao processar PDF.")
        self.set_validation_status("Falha na validacao ou no processamento", warning=True)
        messagebox.showerror("Erro ao processar PDF", error_message)

    # --------------------------------------------------------

    def finish_processing(self):
        self.btn_select.config(state="normal")
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

        self.root.after(120, self.process_queues)

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
    root = tk.Tk()
    AutoOCRApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
