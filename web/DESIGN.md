# DESIGN.md — aiuda Consola

Dirección: **Atelier claro**. Caro por precisión, no por adorno: aire, una escala de letra
que se abre arriba, cifras con peso, casi ningún marco.

## Estrategia de color

Monocromo. Grises neutros (croma residual, 0.001 a 0.004) y **el azul de marca como el
único color del armazón**: acción primaria, selección, enlace y foco. Tema claro (dueño
de PyME, oficina de día, laptop).

Los colores de estado existen, apagados, y van **solo en una marca chica** (un punto de
6px) junto al texto que dice lo mismo con palabras. Nunca son la única señal.

## Tokens (definidos en app/globals.css, OKLCH)

- bg `oklch(0.992 0.001 250)` · panel `oklch(0.966 0.0015 250)` · surface `oklch(0.999 0.0005 250)`
- fill `oklch(0.948 0.002 250)` · fill-strong `oklch(0.915 0.002 250)` (relleno de botón secundario, chip, pista)
- line `oklch(0.925 0.002 250)` · line-strong `oklch(0.845 0.003 250)` · field `oklch(0.655 0.004 250)` (borde de campo, 3:1)
- ink `oklch(0.205 0.004 255)` · ink-2 `oklch(0.4 0.004 255)` · ink-3 `oklch(0.52 0.004 255)`
- accent `oklch(0.52 0.118 236)` · accent-strong · accent-soft · accent-ink
- brand `oklch(0.62 0.105 228)` (≈ #2596be): solo el punto del wordmark
- ok / warn / warn-strong / danger, con variantes -soft casi sin croma

Contraste medido (WCAG): ink sobre bg 17.5 · ink-2 9.0 · ink-3 5.4 (4.7 sobre fill) ·
blanco sobre accent 5.35 · ok 6.4 · warn 5.7 · warn-strong 6.7 · danger 6.6.

## Tipografía

- **SF Pro**, la letra del sistema (`-apple-system`): viene en toda Mac, no se reparte ni
  se descarga nada. El wordmark conserva **Avenir Next** (`.wordmark`), también del sistema.
- **Nunca se escribe un tamaño en píxeles en una pantalla.** Siete niveles con nombre en
  `@theme` y la pantalla pide el PAPEL del texto:

  | clase          | px | para qué                                                |
  | -------------- | -- | ------------------------------------------------------- |
  | `text-cifra`   | 40 | EL número de la pantalla (uno solo). 32 en teléfono      |
  | `text-titulo`  | 28 | el título de la pantalla; un KPI de una fila de varios   |
  | `text-seccion` | 18 | título de una sección, una tarjeta o una fila             |
  | `text-cuerpo`  | 15 | TODO lo que hay que leer. El piso                        |
  | `text-apoyo`   | 14 | dato secundario junto a un cuerpo (fecha, folio, meta)    |
  | `text-rotulo`  | 13 | etiqueta corta: encabezado de tabla, rótulo, marca        |
  | `text-sello`   | 12 | etiqueta de UNA palabra. Nunca prosa                     |

- **12px es el suelo absoluto y solo para una palabra.** El dueño puede tener 50 años y
  presbicia, y lee esto en su monitor, no pegado a él.
- Cifras financieras SIEMPRE con `.tnum`; la protagonista con `.hero-num` (peso 650,
  tracking apretado).
- Rótulos de sección con `.eyebrow`: minúsculas, 13px, gris. Sin versalitas espaciadas.

## Primitivos (clases en app/globals.css, envueltos en components/ui.tsx)

- `.btn` + `.btn-primary` (azul, la única mancha de color) · `.btn-secondary` (relleno
  gris, sin borde) · `.btn-quiet` (solo texto) · `.btn-danger`. Tamaños `.btn-sm` (32),
  normal (40), `.btn-lg` (52). Un botón no se escribe a mano con utilidades.
- `.field`: el único objeto con borde visible, porque es donde se escribe.
- `.mark`: punto + palabra para un estado; el color entra por `--mark`.
- `Tabs`: control segmentado (pista gris, pestaña activa posada encima).
- PageHeader, BucketPill (ya es una marca, no una pill), EmptyState, ErrorState, Skeleton.

## Marcos y elevación

Raya fina para separar renglones; **superficie** (panel gris, tarjeta blanca) para
agrupar. No hay caja dentro de caja. La sombra es neutra y se reserva para lo que flota:
menú, panel lateral, diálogo, y la tarjeta que se arrastra en el tablero.

Radios: 8 (chip, fila) · 10 (botón, campo) · 14 (tarjeta, columna, menú) · 18 (diálogo).

## Layout

Topbar 56px sin raya (negocio, búsqueda ⌘K, manual) + sidebar 240px en `panel`, sin
borde: la separa el cambio de superficie. Contenido con 40px de margen lateral.

## Motion

Tres duraciones (140 / 220 / 360 ms) y una curva de salida (ease-out-quint). Solo
estado: hover, press (el botón cede 2%), entrada de página, panel, fila que se resuelve.
Nada de hover con translate ni con escala.

## Prohibido aquí

Gradientes, blur/glow, sombras de color, pills de colores, versalitas espaciadas, cajas
dentro de cajas, grids de tarjetas idénticas, border-left de acento, em dashes en copy,
`text-[Npx]` (cualquier tamaño de letra clavado en píxeles).
