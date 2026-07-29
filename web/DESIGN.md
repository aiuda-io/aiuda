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
- Base 13px / line-height 1.5. Títulos de página 17px semibold. Cifras 21px semibold.
- Cifras financieras SIEMPRE con `.tnum` (tabular-nums).
- Mono solo para código/API: `font-mono` del sistema.

## Componentes (components/ui.tsx)

PageHeader, BucketPill, PrimaryButton, SecondaryButton, EmptyState, ErrorState, Skeleton,
useApi. Botones: radius 6px, 12.5px medium, sin sombras de color, hover por color.

## Layout

Topbar 48px (tenant switcher, búsqueda ⌘K, docs, notificaciones, avatar) + sidebar 224px
(bg panel, grupos: raíz / Cobranza·Cleo / Plataforma) + main max-w-4xl/5xl px-8.

## Motion

Solo estado: skeleton shimmer al cargar, `row-leaving` (200ms ease-out) al resolver un
elemento. Nada de animaciones de entrada de página ni hover con translate.

## Prohibido aquí

Gradientes decorativos, blur/glow, sombras de color, hero-metric con caja oscura,
grids de tarjetas idénticas, border-left de acento, em dashes en copy.
