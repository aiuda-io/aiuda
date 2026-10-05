# DESIGN.md: aiuda Consola

Dirección: **Atelier claro**. Caro por precisión, no por adorno: papel casi blanco, tinta,
una escala de letra que se abre arriba, cifras con peso, rayas finas y casi ninguna caja.

Lo que esta dirección NO es, dicho por quienes la juzgaron: "un SaaS azul mejor planchado"
y "fichas grises con tarjetas blancas". Las reglas de abajo existen para no volver ahí.

## Las cinco reglas

1. **La jerarquía la dan el tamaño y el peso de la letra, no las cajas.** Si algo importa
   más, crece o pesa más. No se le pone marco, fondo ni color.
2. **Raya fina en vez de fondo gris.** Los renglones y las secciones se separan con una
   raya de 1px (`border-line`) y con aire. Un fondo gris no agrupa: ensucia.
3. **Máximo dos niveles de caja**, y el primero casi nunca hace falta. La página es el
   papel; una tarjeta es la excepción (algo que se arrastra, se elige o flota). Nunca una
   tarjeta dentro de una columna gris.
4. **El acento se usa con avaricia.** En una pantalla, el azul aparece en el botón que la
   resuelve, en el globo de pendientes, en un enlace dentro de un texto y en el foco. Si
   una pantalla tiene más de tres manchas azules, sobra alguna.
5. **Un solo botón relleno por pantalla.** Lo demás es contorno o palabra. En una lista
   de decisiones (Por aprobar en Hoy, Pagos por confirmar) el relleno va en el PRIMER
   renglón; la misma acción en los demás lleva contorno. Así la pantalla dice por dónde
   empezar sin pintar ocho botones azules. Un diálogo cuenta como su propia pantalla:
   su acción va rellena y "Cancelar" es callado.

## Color

Monocromo. Neutros con croma residual hacia el azul de marca, y **el azul de aiuda llevado
a tinta** como único color del armazón. Tema claro únicamente.

Tokens (en `app/globals.css`, OKLCH):

| token | valor | para qué |
| --- | --- | --- |
| `bg` | `0.995 0.001 250` | el papel: el lienzo de toda la consola, menú incluido |
| `surface` | `1 0 0` | lo que flota encima: campo, menú desplegable, diálogo |
| `panel` | `0.975 0.002 250` | banda puntual (un aviso, un pie). No es fondo de columna |
| `fill` | `0.955 0.003 250` | renglón activo o bajo el cursor |
| `fill-strong` | `0.925 0.003 250` | el mismo, presionado; pista de una barra |
| `line` | `0.918 0.003 250` | la raya fina |
| `line-strong` | `0.86 0.004 250` | contorno de botón secundario y de sello |
| `field` | `0.62 0.006 250` | borde de campo, casilla y radio |
| `ink` / `ink-2` / `ink-3` | `0.2` / `0.39` / `0.515` | texto: principal, secundario, apoyo |
| `accent` | `0.44 0.105 238` | el botón primario y el foco |
| `accent-ink` | `0.4 0.1 239` | texto en acento: enlace, globo |
| `warn-band` | `0.945 0.045 85` | la franja del modo de prueba, y nada más |

`brand` (`0.62 0.105 228`, ≈ #2596be) es solo el punto del wordmark.

Los colores de estado (`ok`, `warn`, `warn-strong`, `danger`) van **solo en una marca de
6px** junto a la palabra que dice lo mismo. Nunca son la única señal y nunca son fondo.
La única zona con fondo de color de toda la consola es la franja del modo de prueba.

Contraste medido (WCAG, sobre `bg` salvo que se diga):

- ink 17.8 · ink-2 9.5 · ink-3 5.5 (4.9 sobre `fill`, 5.2 sobre `panel`)
- blanco sobre accent 7.6 · accent-ink 8.9 (7.9 sobre `fill`)
- **borde de campo (`field`): 3.6 sobre `surface` y `bg`, 3.4 sobre `panel`, 3.2 sobre `fill`.**
  Pasa el 3:1 de componentes en cualquier fondo de la consola.
- ok 6.4 · warn 5.8 · warn-strong 6.7 · danger 6.7 · tinta sobre `warn-band` 15.4

## Tipografía

- **SF Pro**, la letra del sistema (`-apple-system`): viene en toda Mac, no se reparte ni
  se descarga nada. El wordmark conserva **Avenir Next** (`.wordmark`). Sin serif.
- **Nunca se escribe un tamaño en píxeles en una pantalla.** Siete niveles con nombre y la
  pantalla pide el PAPEL del texto:

  | clase | px | peso | para qué |
  | --- | --- | --- | --- |
  | `text-cifra` | 44 | 650 (`.hero-num`) | EL número de la pantalla (uno solo). 32 en teléfono |
  | `text-titulo` | 30 | 600 | el título de la pantalla. 25 en teléfono |
  | `text-seccion` | 18 | 600 | título de una sección o de un renglón importante |
  | `text-cuerpo` | 15 | 400, 500 o 600 | TODO lo que hay que leer. El piso |
  | `text-apoyo` | 14 | 400 | dato secundario junto a un cuerpo (fecha, folio) |
  | `text-rotulo` | 13 | 500 | encabezado de tabla, rótulo de sección, estado |
  | `text-sello` | 12 | 500 | etiqueta de UNA o dos palabras. Nunca prosa |

- El salto de 18 a 30 a 44 es grande a propósito: es lo que deja quitar las cajas.
- **12px es el suelo absoluto.** El dueño puede tener 50 años y presbicia.
- Cifras financieras SIEMPRE con `.tnum`; la protagonista con `.hero-num`.
- Rótulos de sección con `.eyebrow`: minúsculas, 13px, gris. Sin versalitas espaciadas.
- Títulos con `text-wrap: balance` y párrafos con `pretty` (ya está en la base).
- Un párrafo no pasa de `max-w-xl`.

## Ritmo

- Aire entre secciones de una página: 40 a 56px (`mt-10` a `mt-14`). Entre el título de una
  sección y su contenido: 12 a 16px. Entre renglones: la raya y 12 a 16px de relleno.
- El encabezado de página (`PageHeader`) deja 40px abajo. Las pestañas dejan 32px.
- Si dos bloques se sienten pegados, se les da aire. No se les pone una raya ni una caja.

## Esquinas: una regla

La medida la pone el TIPO de objeto, y son tres:

| px | tipo | ejemplos |
| --- | --- | --- |
| 6 | etiqueta | sello, chip, casilla |
| 10 | control | botón, campo, renglón que se selecciona |
| 16 | superficie | tarjeta, menú desplegable, panel, diálogo |

Las utilidades de Tailwind están dobladas sobre esas tres (`rounded-sm` y `rounded-md` dan
6, `rounded-lg` da 10, de `rounded-xl` para arriba da 16), así que no hay forma de escribir
una cuarta. `rounded-full` es para puntos y caras. `rounded-[Npx]` está prohibido.

## Primitivos (clases en `app/globals.css`, envueltos en `components/ui.tsx`)

**Botones: tres, en dos tamaños.**

| | clase | componente | cuándo |
| --- | --- | --- | --- |
| primario | `.btn-primary` | `PrimaryButton`, `PrimaryLink` | uno por pantalla: el que la resuelve |
| secundario | `.btn-secondary` | `SecondaryButton`, `SecondaryLink` | contorno fino. Las demás acciones con peso |
| callado | `.btn-quiet` | `QuietButton`, `QuietLink` | solo la palabra. Acciones de renglón, cancelar |

Tamaños: normal (40) y `size="sm"` (32, dentro de un renglón o una tabla). `size="lg"` es
del asistente de primer arranque y de ningún otro lado. `.btn-danger` es el primario de una
confirmación que borra y solo vive dentro de ese diálogo. Un botón no se escribe a mano
con utilidades, y a un `.btn` no se le pone `inline-block` (lo descuadra).

**Barra de acciones: `.barra`.**

Los botones que van juntos (arriba de una página, sobre una lista, al pie de un renglón
que pide una decisión) van en una `.barra`, y el `right` de `PageHeader` ya es una. En
escritorio es una fila, cada botón a su ancho. **En teléfono hay una sola regla, igual en
todas las pantallas:**

- dos botones por renglón, del mismo ancho, de orilla a orilla;
- el que no cabe en media pantalla, o el que queda solo, ocupa el renglón completo;
- el callado se dibuja con contorno, para que no quede una palabra suelta junto a un
  botón. Un callado que va solo ("Eliminar") sigue siendo una palabra;
- el buscador ocupa su propio renglón, de orilla a orilla, arriba de los botones.

Nunca una fila de botones con `flex flex-wrap` a mano: en teléfono se escalona, uno por
renglón y cada uno de un ancho. El relleno sigue siendo uno por pantalla; la barra solo
decide dónde cae cada botón.

**Sello y Estado: las dos únicas etiquetas.**

- `Sello`: una etiqueta neutra que CLASIFICA ("Sin estrenar", "Borrador"). Contorno fino,
  sin relleno y sin color. A lo más uno por renglón, y nunca uno que repita el título de
  la sección donde está.
- `Estado`: cómo VA algo ("Enviado", "No salió", "Vence hoy"). Una palabra y un punto de
  6px con el tono (`neutro`, `ok`, `aviso`, `alerta`, `falla`, `acento`). Sin fondo.

Si te dan ganas de una píldora de color, es un `Estado`. Si no es ninguno de los dos, es
texto. Las etiquetas que el dueño les pone a sus clientes también son un sello: su
color va solo en la marca de 6px, nunca de fondo.

**Lo que se cita y lo que se elige.**

- `.cita`: el mensaje tal como lo va a leer el cliente (y la propuesta de a qué factura
  va un pago). Una raya fina y neutra a la izquierda y aire. Sin caja y sin fondo gris:
  ocho cajas grises en una lista son ocho fichas.
- `.btn-elegida`: la opción puesta de un grupo (tono, canal, fuente, parte de la cara).
  Contorno en tinta y relleno `fill`. Nunca en acento: elegir no es la acción de la
  pantalla.
- Un aviso dentro de una página (falta algo, se detuvo algo) va sobre `panel`, con su
  texto en tinta. No hay bandas ámbar, rojas ni azules: la única zona con color es la
  franja del modo de prueba.

**Lo demás.**

- `.field` (`TextInput`, `inputCls`, `SearchInput`): el único objeto con borde oscuro,
  porque es donde se escribe.
- `Tabs`: palabras sobre una raya; la activa pesa más y lleva su tramo en tinta. Sin pista
  gris. En teléfono se juntan para caber completas (ver "En teléfono"). Para pestañas
  de sección con query, `useQueryTab("vista", [...])` más `hrefFor`: cada pestaña es un
  enlace de verdad. Quien lo use va dentro de `<Suspense>`.
  Ninguna página lee su pestaña de la dirección a mano.
- Una lista de registros es una lista: renglones separados por una raya. Ni una ficha
  gris por renglón ni una columna gris con la fila activa en una tarjeta blanca; el
  renglón activo lleva `fill`.
- Un hilo de mensajes va sobre el papel, sin marco. Lo que llega va sobre `fill`; lo que
  sale, con contorno fino. El acento se guarda para el botón de enviar.
- `PageHeader`, `EmptyState`, `ErrorState`, `Skeleton`, `BucketPill` (ya es una marca).
- `RailLayout` y compañía (`components/rail.tsx`): contenido más riel de contexto.

## El marco

- **Menú** (`components/sidebar.tsx`): 240px, sobre el mismo papel que el contenido, con
  una raya fina a la derecha. Lista plana: Hoy (con su globo), Cartera, Mensajes,
  Clientes, Ayudantes, Ajustes. Productos y Agenda entran antes de Ajustes solo si hay un
  ayudante de Ventas o de Recepción. Sin grupos, sin modos, sin pie. El renglón activo es
  un relleno `fill` y peso 600; también se enciende en rutas hijas, pestañas y
  redirecciones. En teléfono es el mismo menú en un panel, con el manual al pie.
- **Barra superior** (`components/topbar.tsx`): el nombre del negocio, el buscador y el
  manual. 64px, sin raya.
- **Ancho del contenido**: uno solo, `ANCHO_CONTENIDO` en `components/shell.tsx`. 1120px
  útiles más margen (20 en teléfono, 32 en tableta, 40 en escritorio), centrado. Ninguna
  página define su propio ancho máximo de página, Ajustes incluido. Lo que sí se acota es
  el texto corrido y los formularios: la columna de controles de `SettingsSection` se
  queda en medida de lectura, salvo que lleve una lista o una tabla (`ancho`).
- **Modo de prueba** (`components/shadow-banner.tsx`): una franja ámbar de lado a lado,
  fija arriba, "Modo de prueba: nada sale a tus clientes", con "Apagar".
- **Destinos y nombres**: `lib/sections.ts` es la fuente única. De ahí salen el menú, el
  buscador y el Rastro. Un destino nuevo se agrega ahí y en ningún otro lado.
- **Un solo regreso** (`components/rastro.tsx`): las pantallas sin renglón en el menú
  llevan arriba "Volver a…", y es el único. Regresa a donde venías; si llegaste directo
  (un enlace, una recarga), a la puerta bajo la que vive esa pantalla ("Volver a
  Cartera" desde el SAT). Ninguna página pinta su propio regreso encima, y la que ya
  trae su única salida (la de "esta pantalla no existe") lo quita con `useSinRegreso`.

## En teléfono

La consola se usa también desde el celular (390px). Lo que cambia ahí, y nada más:

- **Área táctil de 44 por 44.** Con el dedo (`pointer: coarse`) el botón normal y el
  campo miden 44 de alto. Lo que es chico a propósito (botón de renglón de 32, enlace de
  una palabra, la equis de un panel, un interruptor) conserva su tamaño a la vista y gana
  un área invisible, centrada, que es la que recibe el dedo. Sale sola de
  `app/globals.css` para todo `a`, `button` y `[role]` interactivo: no se le pone nada a
  mano. Lo único que la rompe es `overflow: hidden` en el propio elemento (un `truncate`
  en un enlace): el recorte va en un `span` adentro.
- **Las barras de acciones** siguen la regla de `.barra` (arriba).
- **Las pestañas caben completas.** Se juntan y bajan a `text-apoyo`. Si un grupo nuevo no
  cabe en 350px se le acorta el nombre; no se deja una pestaña cortada ni una fila que haya
  que adivinar que se desliza.
- **Nada se desliza de lado y nada trae scroll propio.** Una tabla que no cabe se vuelve
  lista (Clientes, Productos, Cartera); el hilo de la ficha de un cliente enseña los
  últimos mensajes sobre la página y el resto queda en Mensajes. Las únicas superficies con
  scroll propio son las que flotan: panel lateral, diálogo y la pantalla de chat.
- **El texto no se corta.** Un nombre largo se dobla en los renglones que pida; los puntos
  suspensivos son para una celda de tabla en escritorio, con el nombre completo en `title`.
- **El título y la cifra bajan un escalón** (25 y 32).

## Datos en pantalla

- **Fechas**: siempre por `lib/format.ts`. "2 oct", "2 oct 2026", "2 oct, 10:11". Sin
  cero a la izquierda, sin guion y sin "a.m.". Toda hora que manda el servidor es UTC
  y se lee con `instante`; la de una cita es de reloj y se lee con `deReloj`.
- **Dinero**: siempre con `dinero(monto, moneda)` de `lib/cartera.ts`. Pesos sale
  "$1,234.00"; cualquier otra moneda lleva su código por delante. Dos monedas nunca se
  suman: la principal va grande y la otra en su propio renglón.
- **Teléfonos**: `telefonoMx`. Nunca el número crudo de trece dígitos, tampoco como
  nombre de una conversación sin identificar.
- **Citas**: `fechaCita`. "lun 5 oct, 16:00": reloj de 24 horas, sin "p.m.".
- **Otros datos** (lo que no cupo en nombre, teléfono y correo): la llave se enseña con
  `etiquetaDato`. "municipio" es "Municipio", "dias_credito" es "Días de crédito"; lo que
  el dueño escribió en su Excel se respeta tal cual, y una llave de máquina desconocida se
  separa en palabras. Nunca la llave cruda.
- **De dónde viene un registro** (`ProvenanceBar`): una línea de texto con su marca, sin
  caja ni relleno. Es un dato, no un aviso.

## Elevación

La sombra es neutra y se reserva para lo que flota: menú desplegable, panel lateral,
diálogo, buscador, y la tarjeta mientras se arrastra. Nada apoyado en la página lleva
sombra.

## Motion

Tres duraciones (140 / 220 / 360 ms) y una curva de salida (ease-out-quint). Solo estado:
hover, press (el botón cede 2%), entrada de página, panel, fila que se resuelve. Nada de
hover con translate ni con escala.

## Prohibido aquí

Gradientes, blur y glow, sombras de color, píldoras de colores, fondos de color por estado,
columnas grises con tarjetas blancas, cajas dentro de cajas, grids de tarjetas idénticas,
border-left de acento, versalitas espaciadas, rayas largas en el texto, serif, tema
oscuro, `text-[Npx]` y `rounded-[Npx]`, dos regresos en la misma pantalla, y una opción
elegida pintada de azul.
