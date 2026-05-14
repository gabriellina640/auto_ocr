AUTO OCR PDF

Cria uma copia pesquisavel de um PDF do SAJ sem alterar o arquivo original.

Fluxo para o usuario:

1. Abrir o AutoOCRPDF.exe
2. Selecionar ou arrastar o PDF
3. Aguardar o processamento automatico
4. Abrir arquivo_OCR.pdf

Nao existem configuracoes para o usuario final. O app usa automaticamente o modo de maior fidelidade visual para PDFs do SAJ.

O PDF final recebe camada de texto pesquisavel/selecionavel e passa por validacao tecnica antes de ser liberado.
Durante o processamento, o botao Cancelar OCR interrompe a geracao e remove arquivos temporarios.

VALIDACOES DO APP

Antes de publicar o resultado, o app confere:

- PDF final existe e pode ser aberto
- quantidade de paginas nao mudou
- tamanho das paginas foi preservado dentro de tolerancia
- existe texto pesquisavel extraivel no PDF final

Se a validacao falhar, o PDF temporario nao substitui o resultado final.

EXE WINDOWS

O EXE Windows e gerado pelo GitHub Actions.

No GitHub, abra a aba Actions e rode:

Build Windows EXE

O workflow gera o artifact:

AutoOCRPDF-Windows

Dentro do artifact fica:

AutoOCRPDF.exe

Esse EXE ja e gerado com Tesseract e idioma portugues embutidos pelo proprio workflow.

DESENVOLVIMENTO LOCAL

python3 -m pip install -r requirements.txt
python3 app.py

SEGURANCA

- O original nunca e sobrescrito.
- O resultado e salvo na pasta do app com sufixo _OCR.
- Se ja existir, o app adiciona timestamp.
- O app nao remove senha, nao quebra protecao e nao desbloqueia assinatura.
- PDFs assinados podem gerar uma copia visual com OCR, mas a assinatura digital nao permanece valida nessa copia.
