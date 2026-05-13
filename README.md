AUTO OCR PDF

Cria uma copia OCR de um PDF sem alterar o arquivo original.

Entrada:
arquivo.pdf

Saida:
arquivo_OCR.pdf

O PDF final recebe camada de texto pesquisavel/selecionavel e passa por validacao tecnica antes de ser liberado.

MODOS

1. Compatibilidade segura

Modo recomendado para PDFs escaneados, SAJ, assinados ou bloqueados para copia.
Ele renderiza cada pagina como imagem, aplica OCR e recria o PDF preservando quantidade e tamanho das paginas.

Observacao: a copia OCR pode perder assinatura digital, links, marcadores, formularios e metadados do PDF original.

2. Preservacao maxima

Usa OCRmyPDF quando disponivel.
Tenta manter melhor a estrutura original, mas pode falhar em PDFs protegidos, assinados ou problemáticos.

VALIDACOES DO APP

Antes de publicar o resultado, o app confere:

- PDF final existe e pode ser aberto
- quantidade de paginas nao mudou
- tamanho das paginas foi preservado dentro de tolerancia
- existe texto pesquisavel extraivel no PDF final

Se a validacao falhar, o PDF temporario nao substitui o resultado final.

EXE WINDOWS INTEGRADO

O EXE Windows e gerado pelo GitHub Actions.

Quando o projeto estiver no GitHub, abra a aba Actions e rode:

Build Windows EXE

O workflow gera o arquivo:

AutoOCRPDF-Windows

Dentro do artifact fica:

AutoOCRPDF.exe

Esse EXE ja e gerado com Tesseract e idioma portugues embutidos pelo proprio workflow.

IMPORTANTE SOBRE DEPENDENCIAS

O modo compatibilidade segura depende de:

- Python durante o build no GitHub Actions
- PyInstaller durante o build no GitHub Actions
- Tesseract embutido no EXE pelo workflow
- arquivo por.traineddata embutido no EXE pelo workflow

O modo preservacao maxima tambem depende de OCRmyPDF, Ghostscript e qpdf.
Para distribuicao simples em Windows, trate esse modo como opcional.

DESENVOLVIMENTO LOCAL

python3 -m pip install -r requirements.txt
python3 app.py

SEGURANCA

- O original nunca e sobrescrito.
- O resultado e salvo com sufixo _OCR.
- Se ja existir, o app adiciona timestamp.
- O app nao remove senha, nao quebra protecao e nao desbloqueia assinatura.
- PDFs assinados podem gerar uma copia visual com OCR, mas a assinatura digital nao permanece valida nessa copia.
