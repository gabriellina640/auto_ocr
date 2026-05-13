import os
import sys
import shutil
import queue
import threading
import subprocess
from pathlib import Path
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from pypdf import PdfWriter, PdfReader


APP_NAME = "Auto OCR PDF"
APP_VERSION = "1.0.0"
DEFAULT_DPI = 300


# ============================================================
# UTILITÁRIOS
# ============================================================

def is_windows() -> bool:
    return os.name == "nt"


def is_macos() -> bool:
    return sys.platform == "darwin"


def find_executable(name: str) -> str | None:
    return shutil.which(name)


def open_file(path: Path):
    try:
        if is_windows():
            os.startfile(path)
        elif is_macos():
            subprocess.run(["open", str(path)])
        else:
            subprocess.run(["xdg-open", str(path)])
    except Exception as e:
        messagebox.showerror("Erro", f"Não foi possível abrir o arquivo:\n\n{e}")


def open_folder(path: Path):
    try:
        folder = path if path.is_dir() else path.parent

        if is_windows():
            os.startfile(folder)
        elif is_macos():
            subprocess.run(["open", str(folder)])
        else:
            subprocess.run(["xdg-open", str(folder)])
    except Exception as e:
        messagebox.showerror("Erro", f"Não foi possível abrir a pasta:\n\n{e}")


def safe_output_path(input_pdf: Path) -> Path:
    base = input_pdf.with_name(f"{input_pdf.stem}_OCR.pdf")

    if not base.exists():
        return base

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return input_pdf.with_name(f"{input_pdf.stem}_OCR_{timestamp}.pdf")


def check_tesseract() -> tuple[bool, str]:
    """
    Procura o Tesseract em caminhos comuns.
    Compatível com:
    - macOS Apple Silicon
    - macOS Intel
    - Linux
    - Windows
    """
    possible_paths = [
        "tesseract",
        "/opt/homebrew/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/usr/bin/tesseract",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]

    for path in possible_paths:
        try:
            if path != "tesseract" and not Path(path).exists():
                continue

            pytesseract.pytesseract.tesseract_cmd = path
            version = pytesseract.get_tesseract_version()

            try:
                langs = pytesseract.get_languages(config="")
            except Exception:
                langs = []

            if "por" not in langs:
                return False, (
                    f"Tesseract encontrado em:\n{path}\n\n"
                    f"Versão:\n{version}\n\n"
                    "Mas o idioma português não foi encontrado.\n\n"
                    "No macOS, instale com:\n"
                    "brew install tesseract-lang\n\n"
                    "Depois teste:\n"
                    "tesseract --list-langs\n\n"
                    "Precisa aparecer: por"
                )

            return True, f"Tesseract encontrado em {path} | versão {version}"

        except Exception:
            continue

    return False, (
        "Tesseract OCR não foi encontrado.\n\n"
        "No macOS, instale com:\n"
        "brew install tesseract\n"
        "brew install tesseract-lang\n\n"
        "No Windows, instale o Tesseract OCR e marque a opção de adicionar ao PATH.\n\n"
        "Depois teste no terminal:\n"
        "tesseract --version\n"
        "tesseract --list-langs\n\n"
        "O idioma português precisa aparecer como: por"
    )


def check_ocrmypdf() -> tuple[bool, str]:
    found = find_executable("ocrmypdf")

    if not found:
        return False, "OCRmyPDF não encontrado no PATH."

    try:
        result = subprocess.run(
            ["ocrmypdf", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        return True, f"OCRmyPDF encontrado: {result.stdout.strip()}"
    except Exception as e:
        return False, f"OCRmyPDF encontrado, mas falhou ao executar: {e}"


def pil_image_from_pixmap(pix: fitz.Pixmap) -> Image.Image:
    if pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)

    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


# ============================================================
# PROCESSAMENTO OCR
# ============================================================

def run_ocrmypdf_preservation_mode(
    input_pdf: Path,
    output_pdf: Path,
    language: str,
    progress_callback,
) -> None:
    """
    Modo preservação:
    Usa OCRmyPDF para tentar manter a estrutura original.
    Pode falhar em PDFs assinados/protegidos.
    """
    progress_callback("Iniciando modo preservação...")

    command = [
        "ocrmypdf",
        "--language",
        language,
        "--skip-text",
        "--output-type",
        "pdf",
        str(input_pdf),
        str(output_pdf),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            "O modo preservação não conseguiu processar este PDF.\n\n"
            "Isso pode acontecer com PDF assinado, protegido ou gerado pelo SAJ.\n\n"
            "Use o modo compatibilidade.\n\n"
            f"Detalhe técnico:\n{error_text}"
        )

    progress_callback("PDF OCR criado com sucesso.")


def run_compatibility_mode(
    input_pdf: Path,
    output_pdf: Path,
    language: str,
    dpi: int,
    progress_callback,
    progress_percent_callback,
) -> None:
    """
    Modo compatibilidade:
    Renderiza cada página como imagem e aplica OCR.
    É o mais indicado para PDFs escaneados, SAJ, assinados ou problemáticos.
    """
    progress_callback("Abrindo PDF...")

    document = fitz.open(str(input_pdf))
    total_pages = document.page_count

    if total_pages == 0:
        document.close()
        raise RuntimeError("O PDF não possui páginas.")

    writer = PdfWriter()
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    temp_dir = output_pdf.parent / f"__ocr_temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        for page_index in range(total_pages):
            page_number = page_index + 1

            progress_callback(f"Renderizando página {page_number} de {total_pages}...")
            page = document.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image = pil_image_from_pixmap(pix)

            progress_callback(f"Aplicando OCR na página {page_number} de {total_pages}...")

            pdf_bytes = pytesseract.image_to_pdf_or_hocr(
                image,
                extension="pdf",
                lang=language,
                config="--psm 6",
            )

            temp_page_pdf = temp_dir / f"page_{page_number:05d}.pdf"
            temp_page_pdf.write_bytes(pdf_bytes)

            reader = PdfReader(str(temp_page_pdf))
            writer.add_page(reader.pages[0])

            percent = int((page_number / total_pages) * 100)
            progress_percent_callback(percent)

        progress_callback("Salvando PDF final...")

        with open(output_pdf, "wb") as f:
            writer.write(f)

    finally:
        document.close()
        shutil.rmtree(temp_dir, ignore_errors=True)

    progress_percent_callback(100)
    progress_callback("PDF OCR criado com sucesso.")


# ============================================================
# INTERFACE
# ============================================================

class AutoOCRApp:
    def __init__(self, root: tk.Tk):
        self.root = root

        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("920x640")
        self.root.minsize(880, 620)

        self.selected_pdf: Path | None = None
        self.output_pdf: Path | None = None
        self.worker_thread: threading.Thread | None = None

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.progress_queue: queue.Queue[int] = queue.Queue()

        self.language_var = tk.StringVar(value="por")
        self.mode_var = tk.StringVar(value="compat")
        self.dpi_var = tk.StringVar(value=str(DEFAULT_DPI))

        self.setup_style()
        self.create_layout()
        self.process_queues()

    # --------------------------------------------------------

    def setup_style(self):
        style = ttk.Style()

        try:
            if is_macos():
                style.theme_use("aqua")
            else:
                style.theme_use("clam")
        except Exception:
            pass

        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
        style.configure("Card.TFrame", relief="flat")
        style.configure("Primary.TButton", font=("Segoe UI", 11, "bold"))
        style.configure("Secondary.TButton", font=("Segoe UI", 10))
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Hint.TLabel", font=("Segoe UI", 9))

    # --------------------------------------------------------

    def create_layout(self):
        main = ttk.Frame(self.root, padding=24)
        main.pack(fill="both", expand=True)

        # Header
        header = ttk.Frame(main)
        header.pack(fill="x")

        title = ttk.Label(
            header,
            text="Auto OCR PDF",
            style="Title.TLabel",
        )
        title.pack(anchor="w")

        subtitle = ttk.Label(
            header,
            text="Transforme PDFs escaneados em arquivos pesquisáveis e com texto selecionável.",
            style="Subtitle.TLabel",
        )
        subtitle.pack(anchor="w", pady=(4, 0))

        # Conteúdo principal
        content = ttk.Frame(main)
        content.pack(fill="both", expand=True, pady=(22, 0))

        left = ttk.Frame(content)
        left.pack(side="left", fill="both", expand=True)

        right = ttk.Frame(content, width=300)
        right.pack(side="right", fill="y", padx=(22, 0))
        right.pack_propagate(False)

        self.create_file_card(left)
        self.create_progress_card(left)
        self.create_log_card(left)

        self.create_options_card(right)
        self.create_actions_card(right)
        self.create_help_card(right)

    # --------------------------------------------------------

    def create_file_card(self, parent):
        card = ttk.LabelFrame(parent, text="1. Selecione o PDF")
        card.pack(fill="x")

        upload_area = tk.Frame(
            card,
            bg="#f4f6f8",
            highlightbackground="#c9d1d9",
            highlightthickness=1,
            height=150,
        )
        upload_area.pack(fill="x", padx=14, pady=14)
        upload_area.pack_propagate(False)

        icon = tk.Label(
            upload_area,
            text="📄",
            font=("Segoe UI Emoji", 34),
            bg="#f4f6f8",
        )
        icon.pack(pady=(18, 4))

        self.file_title_label = tk.Label(
            upload_area,
            text="Nenhum PDF selecionado",
            font=("Segoe UI", 12, "bold"),
            bg="#f4f6f8",
            fg="#111827",
        )
        self.file_title_label.pack()

        self.file_path_label = tk.Label(
            upload_area,
            text="Clique no botão abaixo para escolher um arquivo PDF",
            font=("Segoe UI", 9),
            bg="#f4f6f8",
            fg="#6b7280",
            wraplength=560,
        )
        self.file_path_label.pack(pady=(4, 10))

        buttons = ttk.Frame(upload_area)
        buttons.pack()

        self.btn_select = ttk.Button(
            buttons,
            text="Selecionar PDF",
            command=self.select_pdf,
            style="Primary.TButton",
        )
        self.btn_select.pack(side="left", padx=4)

        self.btn_clear = ttk.Button(
            buttons,
            text="Limpar",
            command=self.clear_pdf,
            state="disabled",
        )
        self.btn_clear.pack(side="left", padx=4)

    # --------------------------------------------------------

    def create_options_card(self, parent):
        card = ttk.LabelFrame(parent, text="2. Configurações")
        card.pack(fill="x")

        mode_label = ttk.Label(card, text="Modo de processamento:")
        mode_label.pack(anchor="w", padx=14, pady=(14, 4))

        rb_compat = ttk.Radiobutton(
            card,
            text="Recomendado para SAJ",
            variable=self.mode_var,
            value="compat",
        )
        rb_compat.pack(anchor="w", padx=14)

        compat_hint = ttk.Label(
            card,
            text="Mais compatível com PDFs assinados, escaneados ou bloqueados para cópia.",
            wraplength=250,
            style="Hint.TLabel",
        )
        compat_hint.pack(anchor="w", padx=34, pady=(0, 8))

        rb_preserve = ttk.Radiobutton(
            card,
            text="Preservação máxima",
            variable=self.mode_var,
            value="preserve",
        )
        rb_preserve.pack(anchor="w", padx=14)

        preserve_hint = ttk.Label(
            card,
            text="Tenta manter a estrutura original, mas pode falhar em PDF protegido.",
            wraplength=250,
            style="Hint.TLabel",
        )
        preserve_hint.pack(anchor="w", padx=34, pady=(0, 12))

        ttk.Separator(card).pack(fill="x", padx=14, pady=6)

        lang_label = ttk.Label(card, text="Idioma do OCR:")
        lang_label.pack(anchor="w", padx=14, pady=(8, 4))

        lang_entry = ttk.Entry(card, textvariable=self.language_var)
        lang_entry.pack(fill="x", padx=14)

        lang_hint = ttk.Label(
            card,
            text="Português: por | Português + Inglês: por+eng",
            wraplength=250,
            style="Hint.TLabel",
        )
        lang_hint.pack(anchor="w", padx=14, pady=(4, 10))

        dpi_label = ttk.Label(card, text="Qualidade no modo SAJ:")
        dpi_label.pack(anchor="w", padx=14, pady=(8, 4))

        dpi_combo = ttk.Combobox(
            card,
            textvariable=self.dpi_var,
            values=["200", "300", "400", "500"],
            state="readonly",
        )
        dpi_combo.pack(fill="x", padx=14)

        dpi_hint = ttk.Label(
            card,
            text="300 é o recomendado. 400 aumenta a qualidade e o tamanho do arquivo.",
            wraplength=250,
            style="Hint.TLabel",
        )
        dpi_hint.pack(anchor="w", padx=14, pady=(4, 14))

    # --------------------------------------------------------

    def create_progress_card(self, parent):
        card = ttk.LabelFrame(parent, text="3. Progresso")
        card.pack(fill="x", pady=(18, 0))

        self.status_label = ttk.Label(
            card,
            text="Aguardando seleção do PDF...",
            style="Status.TLabel",
        )
        self.status_label.pack(anchor="w", padx=14, pady=(14, 6))

        self.progress = ttk.Progressbar(
            card,
            mode="determinate",
            maximum=100,
            value=0,
        )
        self.progress.pack(fill="x", padx=14, pady=(0, 6))

        self.progress_percent_label = ttk.Label(
            card,
            text="0%",
        )
        self.progress_percent_label.pack(anchor="e", padx=14, pady=(0, 14))

    # --------------------------------------------------------

    def create_actions_card(self, parent):
        card = ttk.LabelFrame(parent, text="3. Ações")
        card.pack(fill="x", pady=(18, 0))

        self.btn_process = ttk.Button(
            card,
            text="Gerar PDF com OCR",
            command=self.start_processing,
            state="disabled",
            style="Primary.TButton",
        )
        self.btn_process.pack(fill="x", padx=14, pady=(14, 8), ipady=6)

        self.btn_open_pdf = ttk.Button(
            card,
            text="Abrir PDF final",
            command=self.open_output_pdf,
            state="disabled",
        )
        self.btn_open_pdf.pack(fill="x", padx=14, pady=4)

        self.btn_open_folder = ttk.Button(
            card,
            text="Abrir pasta do resultado",
            command=self.open_output_folder,
            state="disabled",
        )
        self.btn_open_folder.pack(fill="x", padx=14, pady=(4, 14))

    # --------------------------------------------------------

    def create_help_card(self, parent):
        card = ttk.LabelFrame(parent, text="Aviso")
        card.pack(fill="both", expand=True, pady=(18, 0))

        text = (
            "Este app não remove senha, não quebra proteção e não altera "
            "o PDF original.\n\n"
            "Ele cria uma nova cópia visualmente equivalente com camada "
            "de texto pesquisável.\n\n"
            "Para PDFs do SAJ, use o modo recomendado."
        )

        label = ttk.Label(
            card,
            text=text,
            wraplength=250,
            justify="left",
        )
        label.pack(anchor="nw", padx=14, pady=14)

    # --------------------------------------------------------

    def create_log_card(self, parent):
        card = ttk.LabelFrame(parent, text="Log do processamento")
        card.pack(fill="both", expand=True, pady=(18, 0))

        self.log_text = tk.Text(
            card,
            height=10,
            wrap="word",
            state="disabled",
            bg="#0f172a",
            fg="#e5e7eb",
            insertbackground="#ffffff",
            relief="flat",
            font=("Menlo", 10) if is_macos() else ("Consolas", 10),
        )
        self.log_text.pack(fill="both", expand=True, padx=14, pady=14)

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

        self.file_title_label.config(text=self.selected_pdf.name)
        self.file_path_label.config(text=str(self.selected_pdf))

        self.btn_clear.config(state="normal")
        self.btn_process.config(state="normal")
        self.btn_open_pdf.config(state="disabled")
        self.btn_open_folder.config(state="disabled")

        self.set_progress(0)
        self.log(f"PDF selecionado: {self.selected_pdf}")

    # --------------------------------------------------------

    def clear_pdf(self):
        self.selected_pdf = None
        self.output_pdf = None

        self.file_title_label.config(text="Nenhum PDF selecionado")
        self.file_path_label.config(text="Clique no botão abaixo para escolher um arquivo PDF")

        self.btn_clear.config(state="disabled")
        self.btn_process.config(state="disabled")
        self.btn_open_pdf.config(state="disabled")
        self.btn_open_folder.config(state="disabled")

        self.set_progress(0)
        self.set_status("Aguardando seleção do PDF...")
        self.log("Seleção limpa.")

    # --------------------------------------------------------

    def validate_inputs(self) -> tuple[bool, str]:
        if self.selected_pdf is None:
            return False, "Selecione um PDF primeiro."

        if not self.selected_pdf.exists():
            return False, "O PDF selecionado não existe."

        if self.selected_pdf.suffix.lower() != ".pdf":
            return False, "O arquivo selecionado precisa ser um PDF."

        language = self.language_var.get().strip()

        if not language:
            return False, "Informe o idioma do OCR. Exemplo: por"

        try:
            dpi = int(self.dpi_var.get().strip())
            if dpi < 100 or dpi > 600:
                return False, "Use um DPI entre 100 e 600."
        except ValueError:
            return False, "DPI inválido. Use um número, exemplo: 300."

        ok_tess, msg_tess = check_tesseract()
        self.log(msg_tess)

        if not ok_tess:
            return False, msg_tess

        if self.mode_var.get() == "preserve":
            ok_ocr, msg_ocr = check_ocrmypdf()
            self.log(msg_ocr)

            if not ok_ocr:
                return False, (
                    "OCRmyPDF não encontrado.\n\n"
                    "Use o modo recomendado para SAJ ou instale OCRmyPDF."
                )

        return True, "OK"

    # --------------------------------------------------------

    def start_processing(self):
        valid, message = self.validate_inputs()

        if not valid:
            messagebox.showerror("Atenção", message)
            return

        self.btn_process.config(state="disabled")
        self.btn_select.config(state="disabled")
        self.btn_clear.config(state="disabled")
        self.btn_open_pdf.config(state="disabled")
        self.btn_open_folder.config(state="disabled")

        self.set_progress(0)
        self.set_status("Iniciando OCR...")
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

            language = self.language_var.get().strip()
            mode = self.mode_var.get()

            try:
                dpi = int(self.dpi_var.get().strip())
            except ValueError:
                dpi = DEFAULT_DPI

            self.log(f"Arquivo de entrada: {input_pdf}")
            self.log(f"Arquivo de saída: {output_pdf}")
            self.log(f"Idioma OCR: {language}")
            self.log(f"Modo: {'Compatibilidade SAJ' if mode == 'compat' else 'Preservação máxima'}")

            if mode == "preserve":
                self.progress_queue.put(10)

                run_ocrmypdf_preservation_mode(
                    input_pdf=input_pdf,
                    output_pdf=output_pdf,
                    language=language,
                    progress_callback=self.log,
                )

                self.progress_queue.put(100)

            else:
                run_compatibility_mode(
                    input_pdf=input_pdf,
                    output_pdf=output_pdf,
                    language=language,
                    dpi=dpi,
                    progress_callback=self.log,
                    progress_percent_callback=lambda value: self.progress_queue.put(value),
                )

            self.log("Processamento concluído.")
            self.root.after(0, self.processing_success)

        except Exception as e:
            error_message = str(e)
            self.log(f"Erro: {error_message}")
            self.root.after(0, lambda: self.processing_error(error_message))

        finally:
            self.root.after(0, self.finish_processing)

    # --------------------------------------------------------

    def processing_success(self):
        self.set_status("PDF OCR criado com sucesso.")
        self.set_progress(100)

        self.btn_open_pdf.config(state="normal")
        self.btn_open_folder.config(state="normal")

        messagebox.showinfo(
            "Concluído",
            f"PDF pesquisável criado com sucesso:\n\n{self.output_pdf}",
        )

    # --------------------------------------------------------

    def processing_error(self, error_message: str):
        self.set_status("Erro ao processar PDF.")
        messagebox.showerror("Erro ao processar PDF", error_message)

    # --------------------------------------------------------

    def finish_processing(self):
        self.btn_select.config(state="normal")

        if self.selected_pdf is not None:
            self.btn_clear.config(state="normal")
            self.btn_process.config(state="normal")

    # --------------------------------------------------------

    def open_output_pdf(self):
        if self.output_pdf and self.output_pdf.exists():
            open_file(self.output_pdf)
        else:
            messagebox.showwarning("Atenção", "Nenhum PDF final encontrado.")

    # --------------------------------------------------------

    def open_output_folder(self):
        if self.output_pdf:
            open_folder(self.output_pdf)
        elif self.selected_pdf:
            open_folder(self.selected_pdf)
        else:
            messagebox.showwarning("Atenção", "Nenhuma pasta disponível.")

    # --------------------------------------------------------

    def log(self, text: str):
        self.log_queue.put(text)

    # --------------------------------------------------------

    def set_status(self, text: str):
        self.status_label.config(text=text)

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