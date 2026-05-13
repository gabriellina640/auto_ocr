OCR DE PDF PESQUISÁVEL

Este programa cria uma cópia OCR de um PDF.
Ele não altera o arquivo original.

Resultado:
arquivo.pdf
arquivo_OCR.pdf

O arquivo _OCR.pdf terá camada de texto pesquisável/selecionável.

REQUISITOS

1. Python instalado
2. Tesseract OCR instalado
3. Idioma português instalado no Tesseract
4. Opcional: OCRmyPDF e Ghostscript para o modo preservação

INSTALAÇÃO DO TESSERACT

No Windows, instale o Tesseract OCR.
Durante a instalação, marque a opção de adicionar ao PATH.

Também instale o pacote de idioma português, chamado "por".

TESTAR O PROGRAMA

Clique duas vezes em:

run_dev.bat

GERAR EXE

Clique duas vezes em:

build.bat

O executável final ficará em:

dist\OCR_PDF.exe

MODOS DO PROGRAMA

1. Compatibilidade SAJ / PDF problemático

Este modo renderiza cada página como imagem e aplica OCR por cima.
É o modo recomendado para PDF do SAJ, assinado ou com bloqueio de cópia.
Ele preserva o conteúdo visual, mas gera uma nova cópia sem preservar assinatura digital.

2. Preservação máxima

Este modo usa OCRmyPDF.
Ele tenta manter a estrutura original do PDF.
Pode falhar em PDFs assinados, protegidos ou problemáticos.

OBSERVAÇÃO IMPORTANTE

O programa não remove senha, não quebra proteção, não desbloqueia assinatura
e não altera o PDF original.

Ele cria uma cópia visualmente equivalente com OCR.