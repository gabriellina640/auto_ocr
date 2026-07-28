> Sistema visual reutilizável inspirado no site **Obromentro**, com foco em interfaces institucionais, dashboards, portais de transparência e acompanhamento de projetos.

---

## 1. Visão geral

O design do Obromentro combina:

- aparência institucional;
- alta legibilidade;
- foco em dados e acompanhamento;
- uso controlado de cor;
- cartões claros sobre fundo neutro;
- fotografia arquitetônica;
- tipografia sem serifa;
- componentes modulares;
- hierarquia visual previsível.

### Palavras-chave

**Clareza, confiança, transparência, precisão, acompanhamento, arquitetura e sobriedade.**

---

## 2. Princípios visuais

### 2.1 Institucional sem parecer burocrático

A interface deve transmitir seriedade sem parecer pesada ou antiquada.

### 2.2 Dados como elemento principal

Números, status, etapas e indicadores devem ter prioridade sobre elementos decorativos.

### 2.3 Cor de assinatura

A cor principal deve ser usada para:

- ações;
- estados ativos;
- progresso;
- títulos de seção;
- destaques;
- indicadores visuais.

Evite utilizar a cor principal em grandes áreas da interface.

### 2.4 Base neutra

A maior parte da interface deve utilizar:

- branco;
- cinza-claro;
- tons de preto;
- bordas discretas.

### 2.5 Hierarquia previsível

Todas as páginas devem repetir os mesmos padrões de:

- títulos;
- cartões;
- espaçamentos;
- botões;
- tabelas;
- status;
- áreas de conteúdo.

---

## 3. Identidade de cor

### 3.1 Paleta principal

| Token | Cor | Uso |
|---|---|---|
| `brand` | `#A5122A` | Ações, títulos, progresso e estados ativos |
| `brand-dark` | `#7E0E20` | Hover, contraste e detalhes gráficos |
| `brand-soft` | `#FBEAEC` | Fundos suaves, ícones e destaques |
| `ink-950` | `#101114` | Áreas escuras e rodapé |
| `ink-900` | `#1A1A1A` | Títulos e valores principais |
| `ink-700` | `#3D3D3D` | Texto principal |
| `ink-500` | `#666B73` | Texto auxiliar |
| `ink-300` | `#C9CDD2` | Elementos desabilitados |
| `line` | `#E3E6EA` | Bordas e divisores |
| `surface` | `#FFFFFF` | Cartões e superfícies |
| `background` | `#F5F6F8` | Fundo geral |
| `background-alt` | `#EDEFF2` | Áreas alternativas |

### 3.2 Estados semânticos

| Estado | Fundo | Texto |
|---|---|---|
| Concluído | `#DFF5E3` | `#1E7137` |
| Em andamento | `#FDECCB` | `#865700` |
| Planejado | `#EDEFF2` | `#555C64` |
| Crítico | `#FBEAEC` | `#A5122A` |

### 3.3 Proporção recomendada

- **60%** fundos neutros;
- **30%** superfícies brancas;
- **8%** tipografia e ícones;
- **2%** cor de assinatura.

---

## 4. Tokens CSS

```css
:root {
  --brand: #a5122a;
  --brand-dark: #7e0e20;
  --brand-soft: #fbeaec;

  --ink-950: #101114;
  --ink-900: #1a1a1a;
  --ink-700: #3d3d3d;
  --ink-500: #666b73;
  --ink-300: #c9cdd2;

  --line: #e3e6ea;
  --surface: #ffffff;
  --background: #f5f6f8;
  --background-alt: #edeff2;

  --success-bg: #dff5e3;
  --success-fg: #1e7137;

  --warning-bg: #fdeccb;
  --warning-fg: #865700;

  --neutral-bg: #edeff2;
  --neutral-fg: #555c64;

  --font-sans: "Inter", "Segoe UI", system-ui, sans-serif;

  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --space-7: 48px;
  --space-8: 64px;

  --radius-card: 14px;
  --radius-button: 8px;
  --radius-pill: 999px;

  --container-max: 1440px;
  --gutter-desktop: 32px;
  --gutter-mobile: 20px;

  --header-height-desktop: 76px;
  --header-height-mobile: 68px;

  --shadow-card:
    0 1px 2px rgba(16, 24, 40, 0.04),
    0 6px 18px rgba(16, 24, 40, 0.055);

  --shadow-hover:
    0 2px 4px rgba(16, 24, 40, 0.06),
    0 12px 28px rgba(16, 24, 40, 0.1);
}