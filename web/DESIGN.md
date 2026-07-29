# DESIGN.md — aiuda Consola

## Estrategia de color

Restrained. Neutrales entintados al hue de marca (~225), acento solo en acción primaria,
selección y estado. Tema claro (dueño de PyME, oficina de día, laptop).

## Tokens (definidos en app/globals.css, OKLCH)

- bg `oklch(0.988 0.002 220)` · panel `oklch(0.972 0.004 220)` · surface `oklch(0.998 0.001 220)`
- line `oklch(0.918 0.007 220)` · line-strong `oklch(0.86 0.01 222)`
- ink `oklch(0.26 0.032 235)` · ink-2 `oklch(0.46 0.022 232)` · ink-3 `oklch(0.6 0.016 230)`
- accent `oklch(0.58 0.1 228)` (≈ #2596be de marca) · accent-strong · accent-soft · accent-ink
- ok / warn / danger con variantes -soft para fondos

## Tipografía

- Única familia: **Avenir Next** (sistema macOS) con fallback `-apple-system, "Segoe UI", system-ui`.
- **Nunca se escribe un tamaño en píxeles en una pantalla.** Hay siete niveles con
  nombre en `@theme` de `app/globals.css` y la pantalla pide el PAPEL del texto:

  | clase          | px | para qué                                                |
  | -------------- | -- | ------------------------------------------------------- |
  | `text-cifra`   | 28 | el número protagonista de la pantalla (un total, un KPI) |
  | `text-titulo`  | 21 | el título de la pantalla                                 |
  | `text-seccion` | 17 | título de una sección, una tarjeta o una fila             |
  | `text-cuerpo`  | 15 | TODO lo que hay que leer. El piso                        |
  | `text-apoyo`   | 14 | dato secundario junto a un cuerpo (fecha, folio, meta)    |
  | `text-rotulo`  | 13 | etiqueta corta: encabezado de tabla, botón chico, rótulo |
  | `text-sello`   | 12 | etiqueta de UNA palabra (pill, badge). Nunca prosa       |

- **12px es el suelo absoluto y solo para una palabra.** Si el texto se lee en
  renglones, es `cuerpo` o `apoyo`. Esto no es gusto: el dueño de una PyME puede
  tener 50 años y presbicia, y lee esto en su monitor, no pegado a él.
- El `body` hereda `cuerpo`, así que lo que no traiga clase se lee igual.
- Cifras financieras SIEMPRE con `.tnum` (tabular-nums); las hero con `.hero-num`.
- Mono solo para código/API: `font-mono` del sistema.

## Componentes (components/ui.tsx)

PageHeader, BucketPill, PrimaryButton, SecondaryButton, EmptyState, ErrorState, Skeleton,
useApi. Botones: radius 6px, `text-cuerpo` medium (`sm` = `rotulo`, `lg` = `seccion`),
sin sombras de color, hover por color.

## Layout

Topbar 48px (tenant switcher, búsqueda ⌘K, docs, notificaciones, avatar) + sidebar 224px
(bg panel, grupos: raíz / Cobranza·Cleo / Plataforma) + main max-w-4xl/5xl px-8.

## Motion

Solo estado: skeleton shimmer al cargar, `row-leaving` (200ms ease-out) al resolver un
elemento. Nada de animaciones de entrada de página ni hover con translate.

## Prohibido aquí

Gradientes decorativos, blur/glow, sombras de color, hero-metric con caja oscura,
grids de tarjetas idénticas, border-left de acento, em dashes en copy,
`text-[Npx]` (cualquier tamaño de letra clavado en píxeles).
